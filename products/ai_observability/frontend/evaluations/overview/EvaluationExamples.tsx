import { LemonTag, type LemonTagType } from '@posthog/lemon-ui'

import { TraceSampleRow } from '../components/TraceSampleRow'
import type { EvaluationExample, ExampleOutcome } from './evaluationResultDrawerLogic'

const OUTCOME_TAGS: Record<Exclude<ExampleOutcome, null>, { label: string; type: LemonTagType }> = {
    passed: { label: 'Passed', type: 'success' },
    failed: { label: 'Failed', type: 'danger' },
    not_applicable: { label: 'N/A', type: 'muted' },
}

/** Recent runs as rows with the trace each one graded. A row opens its trace. */
export function EvaluationExamples({
    examples,
    onOpen,
}: {
    examples: EvaluationExample[]
    onOpen: (example: EvaluationExample) => void
}): JSX.Element {
    if (examples.length === 0) {
        return <div className="text-sm text-secondary">No runs in this range.</div>
    }
    return (
        <div className="-mx-3 -mb-3 divide-y divide-primary border-t border-primary">
            {examples.map((example, index) => {
                const tag = example.outcome ? OUTCOME_TAGS[example.outcome] : null
                return (
                    <TraceSampleRow
                        key={`${example.run.timestamp}-${index}`}
                        sample={example.sample}
                        timestamp={example.run.timestamp}
                        tag={
                            tag ? (
                                <LemonTag type={tag.type} size="small">
                                    {tag.label}
                                </LemonTag>
                            ) : undefined
                        }
                        note={example.run.reasoning ?? 'No reasoning was recorded for this result.'}
                        onOpen={example.run.traceId ? () => onOpen(example) : null}
                        data-attr="evaluation-overview-drawer-trace"
                    />
                )
            })}
        </div>
    )
}
