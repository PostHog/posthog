import { IconChevronDown, IconExpand45, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'

import type { TraceDrawerPosition } from '../traceDrawerLogic'

export interface TraceDrawerToolbarProps {
    showNavigation?: boolean
    /** Null when the open trace is not in the list. */
    position: TraceDrawerPosition | null
    /** Why the open trace is in the list, when the list says. */
    label?: string | null
    onPrevious: (() => void) | null
    onNext: (() => void) | null
    fullPageHref: string
    fullPageInNewTab?: boolean
    onClose: () => void
}

const NOT_IN_LIST_REASON = "This trace isn't in the list"

export function TraceDrawerToolbar({
    showNavigation = true,
    position,
    label,
    onPrevious,
    onNext,
    fullPageHref,
    fullPageInNewTab = false,
    onClose,
}: TraceDrawerToolbarProps): JSX.Element {
    return (
        <div className="flex min-w-0 flex-1 items-center gap-1">
            {showNavigation && (
                <>
                    <LemonButton
                        size="small"
                        icon={<IconChevronDown className="rotate-180" />}
                        tooltip={
                            <>
                                Previous trace <KeyboardShortcut p />
                            </>
                        }
                        aria-label="Previous trace"
                        data-attr="trace-drawer-previous"
                        onClick={onPrevious ?? undefined}
                        disabledReason={
                            onPrevious ? undefined : position ? 'This is the first trace' : NOT_IN_LIST_REASON
                        }
                    />
                    <LemonButton
                        size="small"
                        icon={<IconChevronDown />}
                        tooltip={
                            <>
                                Next trace <KeyboardShortcut n />
                            </>
                        }
                        aria-label="Next trace"
                        data-attr="trace-drawer-next"
                        onClick={onNext ?? undefined}
                        disabledReason={
                            onNext ? undefined : position ? 'This is the last loaded trace' : NOT_IN_LIST_REASON
                        }
                    />
                    {position ? (
                        <span className="ml-1 whitespace-nowrap text-xs text-secondary" aria-live="polite">
                            {`${position.index + 1} of ${position.total}`}
                        </span>
                    ) : null}
                    {label ? (
                        <span
                            className="ml-2 min-w-0 truncate text-xs"
                            title={label}
                            data-attr="trace-drawer-row-label"
                        >
                            {label}
                        </span>
                    ) : null}
                </>
            )}
            <div className="ml-auto flex items-center gap-1">
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconExpand45 />}
                    to={fullPageHref}
                    targetBlank={fullPageInNewTab}
                    data-attr="trace-drawer-full-page"
                >
                    Open full page
                </LemonButton>
                <LemonButton
                    size="small"
                    icon={<IconX />}
                    tooltip={
                        <>
                            Close <KeyboardShortcut escape />
                        </>
                    }
                    aria-label="Close"
                    data-attr="trace-drawer-close"
                    onClick={onClose}
                />
            </div>
        </div>
    )
}
