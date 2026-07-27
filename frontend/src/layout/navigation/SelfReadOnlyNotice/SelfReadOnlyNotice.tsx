// Experiment widget — intentionally reuses ImpersonationNotice's SCSS classes so we can
// iterate on UX cheaply. If this graduates from experiment, promote to a shared
// `FloatingNotice` primitive (or copy the styles into a sibling .scss).
import '../ImpersonationNotice/ImpersonationNotice.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCollapse, IconWarning } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { DraggableWithSnapZones, DraggableWithSnapZonesRef } from 'lib/components/DraggableWithSnapZones'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { IconDragHandle } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

import { ESCALATION_OPTIONS, selfReadOnlyModeLogic } from './selfReadOnlyModeLogic'

// Storybook keeps the same iframe across story switches, and the kea
// `featureFlags` state leaks once any story sets the flag. The global
// `withFeatureFlags` decorator does reset `persisted_feature_flags` per story,
// so use that as a second gate when running in storybook.
function isFlagPersistedInStorybook(): boolean {
    if (typeof window === 'undefined' || !('__mockServiceWorker' in window)) {
        return true // not storybook — defer to the kea-state gate above
    }
    const persisted = (window as { POSTHOG_APP_CONTEXT?: { persisted_feature_flags?: string[] } }).POSTHOG_APP_CONTEXT
        ?.persisted_feature_flags
    return Array.isArray(persisted) && persisted.includes(FEATURE_FLAGS.READ_ONLY_MODE)
}

function CountDown({ until }: { until: number }): JSX.Element {
    const [now, setNow] = useState(() => Date.now())
    const { isVisible } = usePageVisibility()

    useEffect(() => {
        if (!isVisible) {
            return
        }
        setNow(Date.now())
        const interval = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(interval)
    }, [isVisible])

    const remainingMs = Math.max(0, until - now)
    const duration = dayjs.duration(remainingMs)
    const text = duration.hours() > 0 ? duration.format('HH:mm:ss') : duration.format('mm:ss')

    return <span className="tabular-nums text-warning">{text}</span>
}

export function SelfReadOnlyNotice(): JSX.Element | null {
    const { isFlagEnabled, isReadOnly, isEscalated, escalatedUntil } = useValues(selfReadOnlyModeLogic)
    const { escalate, endEscalation } = useActions(selfReadOnlyModeLogic)

    const [isMinimized, setIsMinimized] = useState(false)
    const [isDragging, setIsDragging] = useState(false)
    const draggableRef = useRef<DraggableWithSnapZonesRef>(null)

    if (!isFlagEnabled || !isFlagPersistedInStorybook()) {
        return null
    }

    const title = isReadOnly ? 'Read-only mode' : 'Writes allowed (temporary)'

    return (
        <DraggableWithSnapZones
            ref={draggableRef}
            handle=".ImpersonationNotice__sidebar"
            defaultSnapPosition="bottom-right"
            persistKey="self-read-only-notice-position"
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
                    <Tooltip title={`${title} — click to expand`}>
                        <div className="ImpersonationNotice__minimized-content" onClick={() => setIsMinimized(false)}>
                            <IconWarning className="ImpersonationNotice__minimized-icon" />
                        </div>
                    </Tooltip>
                )}
                {!isMinimized && (
                    <div className="ImpersonationNotice__main">
                        <div className="ImpersonationNotice__header">
                            <IconWarning className="ImpersonationNotice__warning-icon" />
                            <span className="ImpersonationNotice__title">{title}</span>
                            <LemonButton
                                size="xsmall"
                                icon={<IconCollapse />}
                                onClick={() => {
                                    setIsMinimized(true)
                                    draggableRef.current?.trySnapTo('bottom-right')
                                }}
                            />
                        </div>
                        <div className="ImpersonationNotice__content">
                            {isReadOnly ? (
                                <>
                                    <p className="ImpersonationNotice__message">
                                        Edits via UI buttons are blocked. Use Max or the MCP to make changes — or
                                        temporarily allow writes:
                                    </p>
                                    <div className="flex gap-2 justify-end">
                                        {ESCALATION_OPTIONS.map(({ seconds, label }) => (
                                            <LemonButton
                                                key={seconds}
                                                type="secondary"
                                                size="small"
                                                data-attr={`self-read-only-escalate-${seconds}s`}
                                                onClick={() => escalate(seconds)}
                                            >
                                                {label}
                                            </LemonButton>
                                        ))}
                                    </div>
                                </>
                            ) : (
                                <>
                                    <p className="ImpersonationNotice__message">
                                        Writes allowed for the next{' '}
                                        {isEscalated && escalatedUntil ? (
                                            <CountDown until={escalatedUntil} />
                                        ) : (
                                            'moment'
                                        )}
                                        .
                                    </p>
                                    <div className="flex gap-2 justify-end">
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            data-attr="self-read-only-end-escalation"
                                            onClick={() => endEscalation()}
                                        >
                                            Back to read-only
                                        </LemonButton>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </DraggableWithSnapZones>
    )
}
