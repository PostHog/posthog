import './ImpersonationNotice.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCollapse, IconEllipsis, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonMenu, Tooltip } from '@posthog/lemon-ui'

import { DraggableWithSnapZones, DraggableWithSnapZonesRef } from 'lib/components/DraggableWithSnapZones'
import { dayjs } from 'lib/dayjs'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { IconDragHandle } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { userLogic } from 'scenes/userLogic'

import { ExpiredSessionInfo, ImpersonationTicketContext, impersonationNoticeLogic } from './impersonationNoticeLogic'
import { ImpersonationReasonModal } from './ImpersonationReasonModal'

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
    }, [pastCountdown])

    return <span className="tabular-nums text-warning">{countdown}</span>
}

function LoginAsContent({
    ticketContext,
    adminLoginUrl,
}: {
    ticketContext: ImpersonationTicketContext
    adminLoginUrl: string | null
}): JSX.Element {
    const disabledReason = !ticketContext.email
        ? 'This ticket has no associated email'
        : !ticketContext.region
          ? 'Unable to determine region for this ticket, no login available'
          : !adminLoginUrl
            ? 'Unable to determine admin URL'
            : undefined

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
            <div className="flex gap-2 justify-end">
                <LemonButton
                    type="secondary"
                    size="small"
                    tooltip={
                        !disabledReason
                            ? 'This currently redirects to the admin login page, but in future will log you in directly.'
                            : undefined
                    }
                    disabledReason={disabledReason}
                    onClick={() => adminLoginUrl && window.open(adminLoginUrl, '_blank')}
                >
                    Login as {ticketContext.email || 'customer'}
                </LemonButton>
            </div>
        </>
    )
}

function ImpersonationExpiredOverlay({ expiredSessionInfo }: { expiredSessionInfo: ExpiredSessionInfo }): JSX.Element {
    const { isReImpersonating } = useValues(impersonationNoticeLogic)
    const { reImpersonate } = useActions(impersonationNoticeLogic)

    const [readOnly, setReadOnly] = useState(true)

    return (
        <ImpersonationReasonModal
            isOpen
            closable={false}
            title="Impersonation session expired"
            description={`Your session impersonating ${expiredSessionInfo.email} has expired.`}
            confirmText="Re-impersonate"
            loading={isReImpersonating}
            onConfirm={(reason) => reImpersonate(reason, readOnly)}
            cancelButton={{
                label: 'Return to admin',
                status: 'danger',
                onClick: () => {
                    window.location.href = '/admin/'
                },
            }}
        >
            <LemonCheckbox checked={readOnly} onChange={setReadOnly} label="Read-only mode (recommended)" />
        </ImpersonationReasonModal>
    )
}

function ImpersonationNoticeContent(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { logout, loadUser } = useActions(userLogic)
    const { isReadOnly, isUpgradeModalOpen, isImpersonationUpgradeInProgress } = useValues(impersonationNoticeLogic)
    const { closeUpgradeModal, upgradeImpersonation, setSessionExpired } = useActions(impersonationNoticeLogic)

    const handleSessionExpired = (): void => {
        if (user) {
            setSessionExpired({
                email: user.email,
                userId: user.id,
                isImpersonatedUntil: user.is_impersonated_until ?? null,
            })
        }
    }

    return (
        <>
            <p className="ImpersonationNotice__message">
                Signed in as <span className="text-warning">{user?.email}</span>
                {user?.organization?.name && (
                    <>
                        {' '}
                        from <span className="text-warning">{user.organization.name}</span>
                    </>
                )}
                .
                {user?.is_impersonated_until && (
                    <>
                        {' '}
                        Expires in{' '}
                        <CountDown datetime={dayjs(user.is_impersonated_until)} callback={handleSessionExpired} />.
                    </>
                )}
            </p>
            <div className="flex gap-2 justify-end">
                <LemonButton type="secondary" size="small" onClick={() => loadUser()} loading={userLoading}>
                    Refresh
                </LemonButton>
                <LemonButton type="secondary" status="danger" size="small" onClick={() => logout()}>
                    Log out
                </LemonButton>
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
                />
            )}
        </>
    )
}

export function ImpersonationNotice(): JSX.Element | null {
    const { user } = useValues(userLogic)

    const {
        isMinimized,
        isReadOnly,
        isImpersonated,
        isSessionExpired,
        expiredSessionInfo,
        ticketContext,
        adminLoginUrl,
    } = useValues(impersonationNoticeLogic)
    const { minimize, maximize, openUpgradeModal, setPageVisible } = useActions(impersonationNoticeLogic)

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
                            {isImpersonated && isReadOnly && (
                                <LemonMenu
                                    items={[
                                        {
                                            label: 'Upgrade to read-write',
                                            onClick: openUpgradeModal,
                                        },
                                    ]}
                                >
                                    <LemonButton size="xsmall" icon={<IconEllipsis />} />
                                </LemonMenu>
                            )}
                            <LemonButton size="xsmall" icon={<IconCollapse />} onClick={handleMinimize} />
                        </div>
                        <div className="ImpersonationNotice__content">
                            {showLoginAs ? (
                                <LoginAsContent ticketContext={ticketContext!} adminLoginUrl={adminLoginUrl} />
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
