import { IconChevronDown, IconExpand45 } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import type { SessionListItemApi, TracePersonApi, SessionPreviewApi } from '../../../generated/api.schemas'
import type { TraceCellLoad } from '../../shared/cellLoads'
import { IdChip } from '../../trace/components/IdChip'
import { TracePersonCell } from '../../traces/components/TracePersonCell'
import { sessionFacts } from '../sessionFacts'
import { SessionTitle } from './SessionTitle'

// pinned: autocapture dashboards and tests select the header's controls by this value and its suffixes
const DATA_ATTR = 'ai-observability-session'

function stepDisabledReason(step: (() => void) | null, listed: boolean, endReason: string): string | undefined {
    return step ? undefined : listed ? endReason : "This session isn't on this page"
}

/** How a session opened from a list steps to its neighbours and opens on its own page. */
export interface SessionListNavigation {
    /** Null for a session whose id a page link cannot carry. */
    fullPageHref: string | null
    /** Whether the page of the list on screen shows the session. */
    listed: boolean
    onPrevious: (() => void) | null
    onNext: (() => void) | null
}

export interface SessionHeaderProps {
    sessionId: string
    /** The session's facts, or null while they load. */
    item: SessionListItemApi | null
    title: TraceCellLoad<SessionPreviewApi>
    person: TraceCellLoad<TracePersonApi | null>
    conversationOnly: boolean
    onConversationOnlyChange: (conversationOnly: boolean) => void
    /** Left out where the session is not opened from a list. */
    listNavigation?: SessionListNavigation
    /** Reads the title and the person again after either failed, where no list reload does. */
    onRetryDetails?: () => void
}

const RETRY_DETAILS_HINT = "Couldn't load this. Select Retry to try again."

export function SessionHeader({
    sessionId,
    item,
    title,
    person,
    conversationOnly,
    onConversationOnlyChange,
    listNavigation,
    onRetryDetails,
}: SessionHeaderProps): JSX.Element {
    const detailsFailed = title.status === 'error' || person.status === 'error'
    const failedMessage = onRetryDetails ? RETRY_DETAILS_HINT : undefined
    return (
        <header className="flex flex-col gap-1 border-b border-primary px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <div className="min-w-0 flex-1 basis-48 text-base font-semibold">
                    <SessionTitle title={title} failedMessage={failedMessage} />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {listNavigation ? (
                        <div className="flex items-center">
                            <LemonButton
                                size="small"
                                icon={<IconChevronDown className="rotate-180" />}
                                tooltip="Previous session"
                                aria-label="Previous session"
                                data-attr={`${DATA_ATTR}-previous`}
                                onClick={listNavigation.onPrevious ?? undefined}
                                disabledReason={stepDisabledReason(
                                    listNavigation.onPrevious,
                                    listNavigation.listed,
                                    'This is the first session on this page'
                                )}
                            />
                            <LemonButton
                                size="small"
                                icon={<IconChevronDown />}
                                tooltip="Next session"
                                aria-label="Next session"
                                data-attr={`${DATA_ATTR}-next`}
                                onClick={listNavigation.onNext ?? undefined}
                                disabledReason={stepDisabledReason(
                                    listNavigation.onNext,
                                    listNavigation.listed,
                                    'This is the last session on this page'
                                )}
                            />
                        </div>
                    ) : null}
                    <LemonSwitch
                        checked={conversationOnly}
                        onChange={onConversationOnlyChange}
                        label="Conversation only"
                        size="small"
                        // pinned: autocapture dashboards and tests select the switch by this value
                        data-attr="ai-observability-session-conversation-only"
                    />
                    {listNavigation?.fullPageHref ? (
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconExpand45 />}
                            to={listNavigation.fullPageHref}
                            data-attr={`${DATA_ATTR}-full-page`}
                        >
                            Open full page
                        </LemonButton>
                    ) : null}
                </div>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-secondary">
                <IdChip id={sessionId} description="session ID" isSensitive />
                {item ? <span>{sessionFacts(item).join(' · ')}</span> : <LemonSkeleton className="h-4 w-40" />}
                <TracePersonCell
                    person={person.status === 'ready' ? person.value : null}
                    status={person.status}
                    failedMessage={failedMessage}
                />
                {detailsFailed && onRetryDetails ? (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={onRetryDetails}
                        data-attr={`${DATA_ATTR}-retry-details`}
                    >
                        Retry
                    </LemonButton>
                ) : null}
            </div>
        </header>
    )
}
