import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { CreateSuggestionPriorityEnumApi } from '../generated/api.schemas'

export function SuggestionForm(): JSX.Element {
    const { suggestionDraft, suggestionPriority, suggestionSubmitResultLoading } = useValues(autoresearchPipelineLogic)
    const { setSuggestionDraft, setSuggestionPriority, submitSuggestion } = useActions(autoresearchPipelineLogic)
    return (
        <div className="border rounded p-3 space-y-2">
            <div className="text-sm font-semibold">Steer the agent</div>
            <LemonTextArea
                value={suggestionDraft}
                onChange={setSuggestionDraft}
                placeholder="e.g. Try a momentum feature: downloads in the last 7 days over the last 30 days."
                minRows={2}
                maxRows={6}
                data-attr="autoresearch-suggestion-input"
            />
            <div className="flex items-center gap-2">
                <LemonSelect
                    size="small"
                    value={suggestionPriority}
                    onChange={(v) => v && setSuggestionPriority(v)}
                    options={[
                        { value: CreateSuggestionPriorityEnumApi.Consider, label: 'Consider (advisory)' },
                        {
                            value: CreateSuggestionPriorityEnumApi.TryNext,
                            label: 'Try next (before autonomous iterations)',
                        },
                    ]}
                />
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => submitSuggestion()}
                    loading={suggestionSubmitResultLoading}
                    disabledReason={!suggestionDraft.trim() ? 'Write a suggestion first' : undefined}
                >
                    Send suggestion
                </LemonButton>
            </div>
        </div>
    )
}
