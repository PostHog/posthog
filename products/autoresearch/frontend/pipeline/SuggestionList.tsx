import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTag, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import {
    AutoresearchSuggestionApi,
    AutoresearchSuggestionPriorityEnumApi,
    AutoresearchSuggestionStatusEnumApi,
} from '../generated/api.schemas'

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

/** Past suggestions and the agent's response to each. */
export function SuggestionList(): JSX.Element {
    const { suggestions, suggestionsLoading, suggestionsError } = useValues(autoresearchPipelineLogic)
    const { loadSuggestions } = useActions(autoresearchPipelineLogic)
    return suggestionsLoading ? (
        <Spinner />
    ) : suggestionsError ? (
        <LemonBanner
            type="error"
            action={{
                children: 'Retry',
                onClick: () => loadSuggestions(),
                'data-attr': 'autoresearch-model-suggestions-retry',
            }}
        >
            Couldn't load the suggestions. Try again, and if it keeps happening contact support.
        </LemonBanner>
    ) : suggestions.length === 0 ? (
        <div className="text-muted text-sm">No suggestions yet. Send one above to steer the next run.</div>
    ) : (
        <div className="space-y-2">
            {suggestions.map((s: AutoresearchSuggestionApi) => (
                <div key={s.id} className="rounded bg-surface-secondary p-3 space-y-1">
                    <div className="flex items-center gap-2">
                        <LemonTag type={SUGGESTION_STATUS[s.status].type}>{SUGGESTION_STATUS[s.status].label}</LemonTag>
                        <span className="text-xs text-muted">{s.priority ? SUGGESTION_PRIORITY[s.priority] : ''}</span>
                        <span className="text-xs text-muted">{dayjs(s.created_at).fromNow()}</span>
                    </div>
                    <div className="text-sm">{s.prompt}</div>
                    {s.agent_response && <div className="text-sm text-muted italic">Agent: {s.agent_response}</div>}
                </div>
            ))}
        </div>
    )
}
