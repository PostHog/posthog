import { useActions, useValues } from 'kea'

import { Button, Input, Spinner } from '@posthog/quill'

import { TRANSCRIPT_AGENT_LABELS } from '../logics/transcriptAgents'
import { TranscriptFilterIcon } from './TranscriptFilterIcon'
import { TranscriptRow } from './TranscriptRow'
import { TRANSCRIPT_FILTERS, TranscriptFilter, transcriptViewerLogic } from './transcriptViewerLogic'

const FILTER_LABELS: Record<TranscriptFilter, string> = {
    focus: 'Focus',
    all: 'All',
    message: 'Messages',
    user: 'User',
    thinking: 'Thinking',
    tool: 'Tools',
    web: 'Web',
    system: 'System',
}

/** A stored transcript, shown the way the agent session ran: messages, thinking, and tool calls with results. */
export function TranscriptViewer({ organizationId }: { organizationId: string }): JSX.Element {
    const logic = transcriptViewerLogic({ organizationId })
    const { transcript, transcriptLoading, transcriptError, filter, search, counts, visibleEntries, shownEntries } =
        useValues(logic)
    const { setFilter, setSearch, showAllEntries, loadTranscript } = useActions(logic)
    const agentLabel = transcript
        ? (TRANSCRIPT_AGENT_LABELS[transcript.agent as keyof typeof TRANSCRIPT_AGENT_LABELS] ?? transcript.agent)
        : null

    return (
        <div className="transcript-page">
            <header className="transcript-header">
                <a href={`/admin/console/organizations/${organizationId}/`}>← Back to the organization</a>
                <h1>{transcript?.filename ?? 'Agent transcript'}</h1>
                {agentLabel && <p className="transcript-muted">Agent picked at upload: {agentLabel}</p>}
            </header>
            {transcriptLoading ? (
                <div className="transcript-status" role="status">
                    <Spinner aria-hidden="true" /> Loading the transcript…
                </div>
            ) : transcriptError ? (
                <div className="transcript-status" role="alert">
                    <p>{transcriptError}</p>
                    <Button variant="outline" onClick={() => loadTranscript()} data-attr="agent-transcript-retry">
                        Try again
                    </Button>
                </div>
            ) : (
                <div className="transcript">
                    <div className="transcript-toolbar">
                        <fieldset className="transcript-filters" aria-label="Filter transcript">
                            {TRANSCRIPT_FILTERS.map((kind) => (
                                <Button
                                    key={kind}
                                    variant="default"
                                    aria-pressed={filter === kind}
                                    onClick={() => setFilter(kind)}
                                    data-attr={`agent-transcript-filter-${kind}`}
                                >
                                    <TranscriptFilterIcon filter={kind} />
                                    {FILTER_LABELS[kind]} <span>{counts[kind]}</span>
                                </Button>
                            ))}
                        </fieldset>
                        <div className="transcript-options">
                            <Input
                                type="search"
                                aria-label="Search transcript"
                                placeholder="Search transcript"
                                value={search}
                                onChange={(event) => setSearch(event.target.value)}
                            />
                            {search && <Button onClick={() => setSearch('')}>Clear search</Button>}
                        </div>
                    </div>
                    <section className="transcript-scroll" aria-label="Session transcript">
                        {shownEntries.map((entry) => (
                            <TranscriptRow key={entry.id} entry={entry} />
                        ))}
                        {visibleEntries.length > shownEntries.length && (
                            <Button
                                className="load-transcript"
                                variant="outline"
                                onClick={() => showAllEntries()}
                                data-attr="agent-transcript-show-all"
                            >
                                Show {visibleEntries.length - shownEntries.length} more entries
                            </Button>
                        )}
                        {visibleEntries.length === 0 && (
                            <p className="transcript-muted">
                                {counts.all ? 'No entries match this filter and search.' : 'The transcript is empty.'}
                            </p>
                        )}
                    </section>
                </div>
            )}
        </div>
    )
}
