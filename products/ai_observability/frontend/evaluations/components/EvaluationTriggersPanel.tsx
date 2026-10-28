import { useValues } from 'kea'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationTriggers } from './EvaluationTriggers'

/** The condition sets an evaluation runs on, with how they combine and a few examples. */
export function EvaluationTriggersPanel(): JSX.Element | null {
    const { evaluation } = useValues(llmEvaluationLogic)

    if (!evaluation) {
        return null
    }
    const hasFilters = evaluation.conditions.some((condition) => (condition.properties ?? []).length > 0)
    return (
        <div>
            <p className="text-muted text-sm mb-4">
                The evaluation runs on generations that match any one of these condition sets. Within a set, all filters
                must match, and sampling decides how many of the matching generations get evaluated.
                {evaluation.target === 'trace' && (
                    <>
                        {' '}
                        Conditions match individual generations. The whole trace is evaluated once any of its
                        generations matches, and sampling applies per trace.
                    </>
                )}
            </p>
            <EvaluationTriggers />
            {/* Examples help before the first filter. Once someone filters, they only take room. */}
            {!hasFilters && (
                <div className="bg-bg-light border rounded p-3 text-sm mt-6">
                    <h4 className="font-semibold mb-2">Examples:</h4>
                    <ul className="space-y-1 text-muted list-disc list-inside">
                        <li>
                            <strong>10% of all generations:</strong> Set 10% sampling with no filter conditions
                        </li>
                        <li>
                            <strong>5% of one model's generations:</strong> Set 5% sampling with $ai_model containing
                            your model's name
                        </li>
                        <li>
                            <strong>Exclude internal users:</strong> Set 100% sampling with person property is_internal
                            ≠ true
                        </li>
                        <li>
                            <strong>High-cost generations:</strong> Set 100% sampling with $ai_total_cost_usd &gt; 0.01
                        </li>
                    </ul>
                </div>
            )}
        </div>
    )
}
