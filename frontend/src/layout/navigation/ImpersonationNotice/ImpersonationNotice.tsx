import './ImpersonationNotice.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCollapse, IconEllipsis, IconWarning } from '@posthog/icons'
import { LemonButton, LemonMenu, Tooltip } from '@posthog/lemon-ui'

import { DraggableWithSnapZones, DraggableWithSnapZonesRef } from 'lib/components/DraggableWithSnapZones'
import { dayjs } from 'lib/dayjs'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { IconDragHandle } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { userLogic } from 'scenes/userLogic'

import { ImpersonationReasonModal } from './ImpersonationReasonModal'
import { impersonationNoticeLogic } from './impersonationNoticeLogic'

function CountDown({ datetime, callback }: { datetime: dayjs.Dayjs; callback?: () => void }): JSX.Element {
    const [now, setNow] = useState(dayjs())
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

export function ImpersonationNotice(): JSX.Element | null {
    const { user, userLoading } = useValues(userLogic)
    const { logout, loadUser } = useActions(userLogic)

    const { isMinimized, isUpgradeModalOpen, isReadOnly, isImpersonated, isImpersonationUpgradeInProgress } =
        useValues(impersonationNoticeLogic)
    const { minimize, maximize, openUpgradeModal, closeUpgradeModal, upgradeImpersonation, setPageVisible } =
        useActions(impersonationNoticeLogic)

    const { isVisible: isPageVisible } = usePageVisibility()

    const draggableRef = useRef<DraggableWithSnapZonesRef>(null)
    const [isDragging, setIsDragging] = useState(false)

    const handleMinimize = (): void => {
        minimize()
        draggableRef.current?.trySnapTo('bottom-right')
    }

    useEffect(() => {
        setPageVisible(isPageVisible)
    }, [isPageVisible])

    if (!isImpersonated || !user) {
        return null
    }

    return (
        <>
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
                        isReadOnly ? 'ImpersonationNotice--read-only' : 'ImpersonationNotice--read-write'
                    )}
                >
                    <div className="ImpersonationNotice__sidebar">
                        <IconDragHandle className="ImpersonationNotice__drag-handle" />
                    </div>
                    {isMinimized && (
                        <Tooltip title="Signed in as a customer - click to expand">
                            <div className="ImpersonationNotice__minimized-content" onClick={maximize}>
                                <IconWarning className="ImpersonationNotice__minimized-icon" />
                            </div>
                        </Tooltip>
                    )}
                    {!isMinimized && (
                        <div className="ImpersonationNotice__main">
                            <div className="ImpersonationNotice__header">
                                <IconWarning className="ImpersonationNotice__warning-icon" />
                                <span className="ImpersonationNotice__title">
                                    {isReadOnly ? 'Read-only impersonation' : 'Read-write impersonation'}
                                </span>
                                {isReadOnly && (
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
                                <p className="ImpersonationNotice__message">
                                    Signed in as <span className="text-warning">{user.email}</span>
                                    {user.organization?.name && (
                                        <>
                                            {' '}
                                            from <span className="text-warning">{user.organization.name}</span>
                                        </>
                                    )}
                                    .
                                    {user.is_impersonated_until && (
                                        <>
                                            {' '}
                                            Expires in{' '}
                                            <CountDown
                                                datetime={dayjs(user.is_impersonated_until)}
                                                callback={loadUser}
                                            />
                                            .
                                        </>
                                    )}
                                </p>
                                <div className="flex gap-2 justify-end">
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => loadUser()}
                                        loading={userLoading}
                                    >
                                        Refresh
                                    </LemonButton>
                                    <LemonButton type="secondary" status="danger" size="small" onClick={() => logout()}>
                                        Log out
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </DraggableWithSnapZones>

            <ImpersonationReasonModal
                isOpen={isUpgradeModalOpen}
                onClose={closeUpgradeModal}
                onConfirm={upgradeImpersonation}
                title="Upgrade to read-write impersonation"
                description="Read-write mode allows you to make changes on behalf of the user. Please provide a reason for this upgrade."
                confirmText="Upgrade"
                loading={isImpersonationUpgradeInProgress}
            />
        </>
    )
}
