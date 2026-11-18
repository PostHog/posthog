import { LemonTag } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import type { EvaluationOutputConfig, EvaluationOutputType } from '../types'
import { passRatePreview } from './passRatePreview'

export function EvaluationPassRatePreview({
    outputType,
    config,
}: {
    outputType: EvaluationOutputType
    config: EvaluationOutputConfig
}): JSX.Element {
    const runs = passRatePreview(outputType, config)
    const graded = runs.every((run) => run.passes !== null)
    const passed = runs.filter((run) => run.passes).length

    return (
        <div className="flex flex-col gap-1" aria-label="Example results">
            <span className="text-xs text-secondary">Example results</span>
            <div className="flex flex-col rounded border border-primary bg-surface-primary p-1">
                {runs.map((run, index) => (
                    <div key={index} className="flex items-center gap-2 px-1.5 py-0.5 text-xs">
                        <span className="w-10 shrink-0 text-secondary">{`Run ${index + 1}`}</span>
                        {run.fill !== undefined && (
                            // LemonProgress fills its parent, so this span sets its width.
                            <span className="w-16 shrink-0">
                                <LemonProgress
                                    percent={run.fill * 100}
                                    strokeColor={
                                        run.passes === null
                                            ? 'var(--border-bold)'
                                            : run.passes
                                              ? 'var(--success)'
                                              : 'var(--danger)'
                                    }
                                />
                            </span>
                        )}
                        <code className="min-w-0 flex-1 truncate">{run.value}</code>
                        {run.passes !== null && (
                            <LemonTag size="small" type={run.passes ? 'success' : 'danger'}>
                                {run.passes ? 'Pass' : 'Fail'}
                            </LemonTag>
                        )}
                    </div>
                ))}
                <div className="mt-1 border-t px-1.5 pt-1.5 pb-0.5 text-xs">
                    {graded ? (
                        <>
                            {/* Each changing number sits in its own element, so page translation can't leave it stale. */}
                            <span className="font-semibold">
                                Pass rate <span>{`${Math.round((passed / runs.length) * 100)}%`}</span>
                            </span>
                            <span className="text-secondary">
                                {' · '}
                                <span>{`${passed} of ${runs.length} runs`}</span>
                            </span>
                        </>
                    ) : (
                        <span className="text-secondary">No pass rate. Each run records only what it returns.</span>
                    )}
                </div>
            </div>
        </div>
    )
}
