import clsx from 'clsx'

import {
    BaseIcon,
    IconBolt,
    IconCollapse,
    IconCursor,
    IconExpand,
    IconEye,
    IconLeave,
    IconLogomark,
    IconTerminal,
} from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { getExceptionAttributes } from 'lib/components/Errors/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TZLabel } from 'lib/components/TZLabel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { RecordingEventType } from '~/types'

import { SessionEventDetails } from './SessionEventDetails'

// Exception title pill component for compact exception display
function ExceptionTitlePill({ event }: { event: RecordingEventType }): JSX.Element {
    const errorProps = getExceptionAttributes(event.properties || {})

    const type = errorProps.type
    const value = errorProps.value

    if (!type && !value) {
        return <span className="text-muted-alt text-xs">Exception</span>
    }

    return (
        <div className="flex gap-1 px-2 py-0.5 rounded border border-danger-dark bg-danger-highlight text-xs font-mono truncate max-w-md">
            {type && <span className="font-semibold">{type}</span>}
            {type && value && <span>:</span>}
            {value && <span className="truncate">{value}</span>}
        </div>
    )
}

// Event type to icon mapping based on PlayerInspectorListItem pattern
export function eventToIcon(event: string | undefined | null): React.ComponentType {
    switch (event) {
        case '$pageview':
        case '$screen':
            return IconEye
        case '$pageleave':
            return IconLeave
        case '$autocapture':
            return IconBolt
        case '$exception':
        case 'error':
            return IconTerminal
        default:
            // Check if it's a core PostHog event
            if (event && event.startsWith('$')) {
                return IconLogomark
            }
            // Custom events
            if (event !== undefined && event !== null) {
                return IconCursor
            }
            return BaseIcon
    }
}

// Determine highlight color based on event type
// Pattern from playerInspectorLogic.ts
export function getEventHighlightColor(event: RecordingEventType): 'danger' | 'warning' | 'primary' | null {
    const eventName = event.event?.toLowerCase()

    // Exception events get danger highlight
    if (eventName === '$exception' || event.properties?.$exception_message) {
        return 'danger'
    }

    // Console logs - errors and warnings
    const logLevel = event.properties?.$console_log_level
    if (logLevel === 'error') {
        return 'danger'
    }
    if (logLevel === 'warn') {
        return 'warning'
    }

    // Network errors (4xx, 5xx responses)
    const responseStatus = event.properties?.$response_status || event.properties?.status_code
    if (responseStatus && responseStatus >= 400) {
        return 'danger'
    }

    return null
}

export interface SessionEventItemProps {
    event: RecordingEventType
    index: number
    isExpanded: boolean
    onToggleExpand: (index: number) => void
    onLoadEventDetails?: (eventId: string, eventName: string) => void
}

export function SessionEventItem({
    event,
    index,
    isExpanded,
    onToggleExpand,
    onLoadEventDetails,
}: SessionEventItemProps): JSX.Element {
    const EventIcon = eventToIcon(event.event)
    const highlightColor = getEventHighlightColor(event)

    const handleToggle = (): void => {
        if (!isExpanded && !event.fullyLoaded && onLoadEventDetails) {
            onLoadEventDetails(event.id, event.event)
        }
        onToggleExpand(index)
    }

    return (
        <div
            className={clsx(
                'border border-border rounded overflow-hidden transition-all bg-surface-primary',
                !isExpanded && 'hover:bg-secondary-3000-hover-light',
                isExpanded && 'border-accent',
                isExpanded && highlightColor === 'danger' && 'border-danger-dark',
                isExpanded && highlightColor === 'warning' && 'border-warning-dark',
                isExpanded && highlightColor === 'primary' && 'border-primary-dark'
            )}
            style={{
                zIndex: isExpanded ? 1 : 0,
            }}
        >
            <div
                className={clsx(
                    'flex items-center justify-between px-2 py-1 cursor-pointer',
                    highlightColor === 'danger' && 'bg-fill-error-highlight',
                    highlightColor === 'warning' && 'bg-fill-warning-highlight',
                    highlightColor === 'primary' && 'bg-fill-success-highlight'
                )}
                onClick={handleToggle}
            >
                <div className="flex items-center gap-2 flex-1 overflow-hidden">
                    <div className="flex items-center p-0.5">
                        <EventIcon />
                    </div>
                    <TZLabel
                        time={event.timestamp}
                        formatDate="MMMM DD, YYYY"
                        formatTime="h:mm:ss A"
                        showPopover={false}
                        className="text-xs text-muted-alt min-w-32"
                    />
                    <PropertyKeyInfo
                        value={event.event}
                        type={TaxonomicFilterGroupType.Events}
                        className="font-semibold truncate max-w-80"
                        disablePopover
                    />
                    {event.event === '$exception' ? (
                        <ExceptionTitlePill event={event} />
                    ) : (
                        event.properties?.$pathname &&
                        event.properties?.$host && (
                            <span className="text-muted-alt truncate text-xs">
                                - {event.properties.$host}
                                {event.properties.$pathname}
                            </span>
                        )
                    )}
                </div>
                <LemonButton
                    icon={isExpanded ? <IconCollapse /> : <IconExpand />}
                    size="small"
                    noPadding
                    onClick={(e) => {
                        e.stopPropagation()
                        handleToggle()
                    }}
                />
            </div>

            {isExpanded && (
                <div
                    className={clsx(
                        'border-t border-border',
                        highlightColor === 'danger' && 'bg-fill-error-highlight',
                        highlightColor === 'warning' && 'bg-fill-warning-highlight',
                        highlightColor === 'primary' && 'bg-fill-success-highlight'
                    )}
                >
                    <div className="max-h-[400px] overflow-y-auto">
                        <SessionEventDetails event={event} />
                    </div>
                </div>
            )}
        </div>
    )
}
