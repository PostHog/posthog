import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type { QuestionRunResultApi } from './generated/api.schemas'

export function QuestionRunResult({ result }: { result: QuestionRunResultApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 text-sm min-w-0">
            <LemonTag type={result.coverage_complete ? 'muted' : 'warning'}>
                {result.coverage_complete
                    ? result.examined_row_count === 0
                        ? 'No rows in scope'
                        : 'All rows examined'
                    : 'Incomplete coverage'}
            </LemonTag>
            <span>{pluralize(result.examined_row_count, 'row')} examined</span>
            <span>
                {result.completed_chunk_count} / {result.total_chunk_count} batches completed
            </span>
            {result.coverage_complete && result.failure_rate !== null && (
                <span>
                    {pluralize(result.failed_row_count, 'failed row')} ({(result.failure_rate * 100).toFixed(1)}%)
                </span>
            )}
            <Tooltip title="Counts describe distinct model decisions, not exact AI credit charges. Null column values fail without inference.">
                <span className="text-secondary">
                    {result.unique_input_count} distinct inputs, {result.reused_decision_count} decisions reused,{' '}
                    {result.new_decision_count} new
                </span>
            </Tooltip>
        </div>
    )
}
