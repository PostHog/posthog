import { LemonTag } from '@posthog/lemon-ui'

import type { EvalSuggestionApi } from '../../generated/api.schemas'
import { suggestionKindLabel, suggestionKindTagType } from './suggestionKind'

/** What the pipeline noticed: the kind, a headline, what the eval would do, and what the sample showed. */
export function EvaluationSuggestionSummary({ suggestion }: { suggestion: EvalSuggestionApi }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1 py-2">
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag type={suggestionKindTagType(suggestion)} size="small">
                    {suggestionKindLabel(suggestion)}
                </LemonTag>
                {suggestion.kind === 'fix_eval' && (
                    <span className="truncate text-xs text-secondary">
                        {suggestion.target_evaluation_name ?? 'An existing eval'}
                    </span>
                )}
            </div>
            <span className="text-base font-semibold">{suggestion.headline}</span>
            <span className="text-sm text-secondary">{suggestion.outcome}</span>
            {suggestion.observation && (
                <span className="flex flex-wrap items-center gap-x-1.5 text-xs">
                    <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-warning" />
                    <span className="font-medium">{suggestion.observation}</span>
                    {suggestion.observation_scope && (
                        <span className="text-secondary">{`· ${suggestion.observation_scope}`}</span>
                    )}
                </span>
            )}
        </div>
    )
}
