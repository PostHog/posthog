import { useValues } from 'kea'

import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import {
    AutoresearchSuggestionApi,
    AutoresearchSuggestionPriorityEnumApi,
    AutoresearchSuggestionStatusEnumApi,
} from '../generated/api.schemas'
import { SuggestionForm } from './SuggestionForm'

const SUGGESTION_STATUS: Record<
    AutoresearchSuggestionStatusEnumApi,
    { type: 'success' | 'default' | 'danger' | 'highlight'; label: string }
> = {
    queued: { type: 'default', label: 'Queued' },
    picked_up: { type: 'highlight', label: 'Picked up' },
    acted_on: { type: 'success', label: 'Acted on' },
    dismissed: { type: 'danger', label: 'Dismissed' },
}

const SUGGESTION_PRIORITY: Record<AutoresearchSuggestionPriorityEnumApi, string> = {
    consider: 'Consider',
    try_next: 'Try next',
}

export function SuggestionsTab(): JSX.Element {
    const { suggestions, suggestionsLoading } = useValues(autoresearchPipelineLogic)
    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                Inject a free-text hypothesis into the training loop. The agent reads queued suggestions at the start of
                each iteration batch and decides whether to act on, apply, or dismiss each one.
            </p>
            <SuggestionForm />
            {suggestionsLoading ? (
                <Spinner />
            ) : suggestions.length === 0 ? (
                <div className="text-muted text-sm">No suggestions yet. Send one above to steer the next run.</div>
            ) : (
                <div className="space-y-2">
                    {suggestions.map((s: AutoresearchSuggestionApi) => (
                        <div key={s.id} className="border rounded p-3 space-y-1">
                            <div className="flex items-center gap-2">
                                <LemonTag type={SUGGESTION_STATUS[s.status].type}>
                                    {SUGGESTION_STATUS[s.status].label}
                                </LemonTag>
                                <span className="text-xs text-muted">
                                    {s.priority ? SUGGESTION_PRIORITY[s.priority] : ''}
                                </span>
                                <span className="text-xs text-muted">{dayjs(s.created_at).fromNow()}</span>
                            </div>
                            <div className="text-sm">{s.prompt}</div>
                            {s.agent_response && (
                                <div className="text-sm text-muted italic">Agent: {s.agent_response}</div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
