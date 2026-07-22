import './ImpersonationNotice.scss'

import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconChevronDown, IconCollapse, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonMenu, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { DraggableWithSnapZones, DraggableWithSnapZonesRef } from 'lib/components/DraggableWithSnapZones'
import { dayjs } from 'lib/dayjs'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { IconDragHandle } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { capitalizeFirstLetter, fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { OrganizationMemberType } from '~/types'

import { AdminLoginButtons } from './AdminLoginButtons'
import { ExpiredSessionInfo, ImpersonationTicketContext, impersonationNoticeLogic } from './impersonationNoticeLogic'
import { ImpersonationReasonModal, ImpersonationReasonModalCancelButton } from './ImpersonationReasonModal'

// One row in the "Change user" dropdown: name on top, email beneath in muted text, level pill on the right.
function ChangeUserMenuItemLabel({
    member,
    isCurrentUser = false,
}: {
    member: OrganizationMemberType
    isCurrentUser?: boolean
}): JSX.Element {
    return (
        <span className="flex items-center gap-2 justify-between w-full">
            <span className="flex flex-col">
                <span>
                    {fullName(member.user)}
                    {isCurrentUser && <span className="text-muted"> (you)</span>}
                </span>
                <span className="text-xs text-muted">{member.user.email}</span>
            </span>
            <LemonTag>
                {capitalizeFirstLetter(membershipLevelToName.get(member.level) ?? `unknown (${member.level})`)}
            </LemonTag>
        </span>
    )
}

function CountDown({ datetime, callback }: { datetime: dayjs.Dayjs; callback?: () => void }): JSX.Element {
    const [now, setNow] = useState(() => dayjs())
    const { isVisible: isPageVisible } = usePageVisibility()

    const duration = dayjs.duration(datetime.diff(now))
    const pastCountdown = duration.seconds() < 0

    const countdown = pastCountdown
        ? 'Expired'
        : duration.hours() > 0
          ? duration.format('HH:mm:ss')
          : duration.format('mm:ss')

    useEffect(() => {
        if (!isPageVisible) {
            return
        }

        setNow(dayjs())
        const interval = setInterval(() => setNow(dayjs()), 1000)
        return () => clearInterval(interval)
    }, [isPageVisible])

    useEffect(() => {
        if (pastCountdown) {
            callback?.() // oxlint-disable-line react-hooks/exhaustive-deps
        }
    }, [pastCountdown, callback])

    return <span className="tabular-nums">{countdown}</span>
}

function LoginAsContent({ ticketContext }: { ticketContext: ImpersonationTicketContext }): JSX.Element {
    return (
        <>
            <p className="ImpersonationNotice__message">
                {ticketContext.email ? (
                    <>
                        Customer: <span className="text-success">{ticketContext.email}</span>
                    </>
                ) : (
                    'No customer email on this ticket'
                )}
            </p>
            <AdminLoginButtons />
        </>
    )
}

function ImpersonationExpiredOverlay({ expiredSessionInfo }: { expiredSessionInfo: ExpiredSessionInfo }): JSX.Element {
    const { isReImpersonating, expiredSessionFromTicket, returnTicketLabel, returnTicketReason, isReturningToTicket } =
        useValues(impersonationNoticeLogic)
    const { reImpersonate, returnToPostHog, returnToTicket } = useActions(impersonationNoticeLogic)

    const [readOnly, setReadOnly] = useState(true)

    const cancelButton: ImpersonationReasonModalCancelButton =
        expiredSessionFromTicket && returnTicketLabel
            ? {
                  label: returnTicketLabel,
                  onClick: () => returnToTicket(),
                  loading: isReturningToTicket,
              }
            : {
                  label: 'Return to admin',
                  status: 'danger',
                  onClick: () => {
                      window.location.href = '/admin/'
                  },
                  sideAction: {
                      dropdown: {
                          placement: 'top-end',
                          overlay: (
                              <LemonButton fullWidth onClick={() => returnToPostHog()}>
                                  Return to PostHog
                              </LemonButton>
                          ),
                      },
                  },
              }

    return (
        <ImpersonationReasonModal
            isOpen
            closable={false}
            title="Impersonation session expired"
            description={`Your session impersonating ${expiredSessionInfo.email} has expired.`}
            confirmText="Re-impersonate"
            loading={isReImpersonating}
            initialReason={expiredSessionFromTicket ? returnTicketReason : (expiredSessionInfo.reason ?? '')}
            onConfirm={(reason) => reImpersonate(reason, readOnly)}
            cancelButton={cancelButton}
        >
            <LemonCheckbox checked={readOnly} onChange={setReadOnly} label="Read-only mode (recommended)" />
        </ImpersonationReasonModal>
    )
}

function ImpersonationNoticeContent(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { logout, loadUser } = useActions(userLogic)
    const {
        isReadOnly,
        isUpgradeModalOpen,
        isImpersonationUpgradeInProgress,
        orderedMembers,
        hasOtherMembers,
        isChangingUser,
        membersLoading,
        canReturnToTicket,
        returnTicketLabel,
        returnTicketReason,
        isReturningToTicket,
    } = useValues(impersonationNoticeLogic)
    const {
        closeUpgradeModal,
        upgradeImpersonation,
        openUpgradeModal,
        setSessionExpired,
        returnToPostHog,
        changeUser,
        ensureAllMembersLoaded,
        returnToTicket,
    } = useActions(impersonationNoticeLogic)

    // The user the operator picked to switch to; drives the confirm-reason modal.
    const [pendingUserId, setPendingUserId] = useState<number | null>(null)

    // The reason given when impersonation of the current user started (persisted server-side),
    // used to pre-fill the change-user and upgrade modals.
    const storedReason = user?.is_impersonated_reason

    const changeUserItems = [
        ...orderedMembers.map((member) => {
            const isCurrentUser = member.user.uuid === user?.uuid
            return {
                key: member.user.uuid,
                label: <ChangeUserMenuItemLabel member={member} isCurrentUser={isCurrentUser} />,
                disabledReason: isCurrentUser
                    ? "You're currently signed in as this user"
                    : isChangingUser
                      ? 'Switching user…'
                      : undefined,
                // Always confirm via the modal (reason pre-filled) rather than switching silently.
                onClick: isCurrentUser ? undefined : () => setPendingUserId(member.user.id),
            }
        }),
        // Spell out the lone-user case so a single disabled row doesn't look like a bug.
        ...(!hasOtherMembers ? [{ label: membersLoading ? 'Loading…' : 'No other members', disabledReason: ' ' }] : []),
    ]

    const handleSessionExpired = useCallback((): void => {
        if (user) {
            setSessionExpired({
                email: user.email,
                userId: user.id,
                isImpersonatedUntil: user.is_impersonated_until ?? null,
                reason: user.is_impersonated_reason ?? null,
            })
        }
    }, [user, setSessionExpired])

    return (
        <>
            <p className="ImpersonationNotice__message">
                Signed in as{' '}
                <LemonMenu
                    items={changeUserItems}
                    onVisibilityChange={(visible) => visible && ensureAllMembersLoaded()}
                >
                    <LemonButton
                        size="xsmall"
                        sideIcon={<IconChevronDown />}
                        loading={isChangingUser}
                        tooltip={`Currently impersonating ${user?.email} - click to switch user`}
                        truncate
                        className="ImpersonationNotice__inline-trigger ImpersonationNotice__user-trigger text-warning"
                    >
                        {user?.email}
                    </LemonButton>
                </LemonMenu>
                {user?.organization?.name && (
                    <>
                        {' '}
                        from <span className="text-warning">{user.organization.name}</span>
                    </>
                )}
                .
            </p>
            {user?.is_impersonated_until && (
                <div className="ImpersonationNotice__expiry">
                    <span>
                        Expires in{' '}
                        <CountDown datetime={dayjs(user.is_impersonated_until)} callback={handleSessionExpired} />
                    </span>
                    <LemonButton
                        type="secondary"
                        size="xxsmall"
                        icon={<IconRefresh />}
                        onClick={() => loadUser()}
                        loading={userLoading}
                        tooltip="Refresh"
                    />
                </div>
            )}
            <div className="flex gap-2 justify-end">
                {isReadOnly && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => openUpgradeModal()}
                        tooltip="Upgrade your impersonation session to have read-write permissions"
                    >
                        Upgrade to read-write
                    </LemonButton>
                )}
                {canReturnToTicket ? (
                    <LemonButton
                        type="primary"
                        size="small"
                        loading={isReturningToTicket}
                        onClick={() => returnToTicket()}
                    >
                        {returnTicketLabel}
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => logout()}
                        sideAction={{
                            dropdown: {
                                placement: 'top-end',
                                overlay: (
                                    <LemonButton fullWidth size="small" onClick={() => returnToPostHog()}>
                                        Log out to PostHog
                                    </LemonButton>
                                ),
                            },
                        }}
                    >
                        Log out to admin
                    </LemonButton>
                )}
            </div>
            {isReadOnly && (
                <ImpersonationReasonModal
                    isOpen={isUpgradeModalOpen}
                    onClose={closeUpgradeModal}
                    onConfirm={upgradeImpersonation}
                    title="Upgrade to read-write impersonation"
                    description="Read-write mode allows you to make changes on behalf of the user. Please provide a reason for this upgrade."
                    confirmText="Upgrade"
                    loading={isImpersonationUpgradeInProgress}
                    initialReason={canReturnToTicket ? returnTicketReason : (storedReason ?? '')}
                />
            )}
            <ImpersonationReasonModal
                isOpen={pendingUserId !== null}
                onClose={() => setPendingUserId(null)}
                onConfirm={(reason) => {
                    if (pendingUserId !== null) {
                        changeUser(pendingUserId, reason)
                    }
                    setPendingUserId(null)
                }}
                title="Change impersonated user"
                description="Provide a reason for impersonating this user."
                confirmText="Switch user"
                loading={isChangingUser}
                initialReason={storedReason ?? ''}
            />
        </>
    )
}

export function ImpersonationNotice(): JSX.Element | null {
    const { user } = useValues(userLogic)

    const { isMinimized, isReadOnly, isImpersonated, isSessionExpired, expiredSessionInfo, ticketContext } =
        useValues(impersonationNoticeLogic)
    const { minimize, maximize, setPageVisible } = useActions(impersonationNoticeLogic)

    const { isVisible: isPageVisible } = usePageVisibility()

    const draggableRef = useRef<DraggableWithSnapZonesRef>(null)
    const [isDragging, setIsDragging] = useState(false)

    const handleMinimize = (): void => {
        minimize()
        draggableRef.current?.trySnapTo('bottom-right')
    }

    useEffect(() => {
        setPageVisible(isPageVisible)
    }, [isPageVisible, setPageVisible])

    if (isSessionExpired && expiredSessionInfo) {
        return <ImpersonationExpiredOverlay expiredSessionInfo={expiredSessionInfo} />
    }

    // Staff actions (login-as) are now rendered inline in the ticket sidebar via StaffActionsPanel
    const showLoginAs = false

    if (!user || (!isImpersonated && !showLoginAs)) {
        return null
    }

    const title = showLoginAs ? 'Staff actions' : isReadOnly ? 'Read-only impersonation' : 'Read-write impersonation'

    return (
        <DraggableWithSnapZones
            ref={draggableRef}
            handle=".ImpersonationNotice__sidebar"
            defaultSnapPosition="bottom-right"
            persistKey="impersonation-notice-position"
            onDragStart={() => setIsDragging(true)}
            onDragStop={() => setIsDragging(false)}
        >
            <div
                className={cn(
                    'ImpersonationNotice',
                    isDragging && 'ImpersonationNotice--dragging',
                    isMinimized && 'ImpersonationNotice--minimized',
                    showLoginAs
                        ? 'ImpersonationNotice--login-as'
                        : isReadOnly
                          ? 'ImpersonationNotice--read-only'
                          : 'ImpersonationNotice--read-write'
                )}
            >
                <div className="ImpersonationNotice__sidebar">
                    <IconDragHandle className="ImpersonationNotice__drag-handle" />
                </div>
                {isMinimized && (
                    <Tooltip
                        title={
                            showLoginAs
                                ? 'Staff actions - click to expand'
                                : 'Signed in as a customer - click to expand'
                        }
                    >
                        <div className="ImpersonationNotice__minimized-content" onClick={maximize}>
                            <IconWarning className="ImpersonationNotice__minimized-icon" />
                        </div>
                    </Tooltip>
                )}
                {!isMinimized && (
                    <div className="ImpersonationNotice__main">
                        <div className="ImpersonationNotice__header">
                            <IconWarning className="ImpersonationNotice__warning-icon" />
                            <span className="ImpersonationNotice__title">{title}</span>
                            <LemonButton size="xsmall" icon={<IconCollapse />} onClick={handleMinimize} />
                        </div>
                        <div className="ImpersonationNotice__content">
                            {showLoginAs ? (
                                <LoginAsContent ticketContext={ticketContext!} />
                            ) : (
                                <ImpersonationNoticeContent />
                            )}
                        </div>
                    </div>
                )}
            </div>
        </DraggableWithSnapZones>
    )
}
