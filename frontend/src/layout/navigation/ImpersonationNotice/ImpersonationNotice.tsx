import './ImpersonationNotice.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DraggableSnapZones } from 'lib/components/DraggableSnapZones'
import { dayjs } from 'lib/dayjs'
import { useDraggableSnap } from 'lib/hooks/useDraggableSnap'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { IconDragHandle } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { userLogic } from 'scenes/userLogic'

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

    const ref = useRef<HTMLDivElement>(null)

    const { position, isDragging, fixedPosition, snapZones, handlers, setElement } = useDraggableSnap({
        defaultPosition: 'bottom-right',
        persistKey: 'impersonation-notice-position',
    })

    useEffect(() => {
        if (ref.current) {
            setElement(ref.current)
        }
    }, [setElement])

    if (!user?.is_impersonated) {
        return null
    }

    const isReadOnly = user.is_impersonated_read_only

    return (
        <>
            <DraggableSnapZones isDragging={isDragging} snapZones={snapZones} fixedPosition={fixedPosition} />
            <div
                ref={ref}
                className={cn(
                    'ImpersonationNotice',
                    isDragging && 'ImpersonationNotice--dragging',
                    isReadOnly ? 'ImpersonationNotice--read-only' : 'ImpersonationNotice--read-write'
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    left: position.x,
                    top: position.y,
                }}
            >
                <div
                    className="ImpersonationNotice__sidebar"
                    onMouseDown={handlers.onMouseDown}
                    onTouchStart={handlers.onTouchStart}
                >
                    <IconDragHandle className="ImpersonationNotice__drag-handle" />
                </div>
                <div className="ImpersonationNotice__main">
                    <div className="ImpersonationNotice__header">
                        <IconWarning className="ImpersonationNotice__warning-icon" />
                        <span className="ImpersonationNotice__title">
                            {isReadOnly ? 'Read-only impersonation' : 'Read-write impersonation'}
                        </span>
                    </div>
                    <div className="ImpersonationNotice__content">
                        <p className="ImpersonationNotice__message">
                            Signed in as <span className="text-warning">{user.email}</span> from{' '}
                            <span className="text-warning">{user.organization?.name}</span>.
                            {user.is_impersonated_until && (
                                <>
                                    {' '}
                                    Expires in{' '}
                                    <CountDown datetime={dayjs(user.is_impersonated_until)} callback={loadUser} />.
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
                    </div>
                </div>
            </div>
        </>
    )
}
