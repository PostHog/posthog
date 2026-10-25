import { useValues } from 'kea'

import { IconPlay, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

// Placeholder lines in chart coordinates. They hint at what the chart will show, without real data.
const GHOST_LINES = [
    'M0 40 C 80 34, 160 46, 240 38 S 400 30, 480 42 S 640 36, 800 40',
    'M0 90 C 80 96, 160 84, 240 92 S 400 104, 480 96 S 640 88, 800 100',
    'M0 140 C 80 132, 160 148, 240 150 S 400 138, 480 152 S 640 160, 800 156',
]

export function EvaluationChartEmptyState({ pausedRows }: { pausedRows: EvaluationResultApi[] }): JSX.Element {
    const { evaluationUrl } = useValues(evaluationsOverviewLogic)
    // A single paused evaluation is the obvious one to resume. With several, the list below lets people choose.
    const onlyPaused = pausedRows.length === 1 ? pausedRows[0] : null
    return (
        <div className="relative h-96 rounded border-2 border-dotted border-secondary overflow-hidden">
            <svg
                viewBox="0 0 800 200"
                preserveAspectRatio="none"
                className="absolute inset-0 w-full h-full text-[var(--color-border-primary)]"
                aria-hidden
            >
                {GHOST_LINES.map((path) => (
                    <path
                        key={path}
                        d={path}
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={3}
                        vectorEffect="non-scaling-stroke"
                    />
                ))}
            </svg>
            <div className="relative h-full flex items-center justify-center px-4">
                {/* A solid card keeps the placeholder lines from running through the text. */}
                <div className="flex flex-col items-center gap-3 text-center rounded-lg border bg-surface-primary px-6 py-6">
                    <div className="font-semibold text-base">No results in this range</div>
                    <div className="text-secondary max-w-md">
                        {onlyPaused
                            ? 'Turn your evaluation back on, or create a new one, to see results here.'
                            : pausedRows.length > 1
                              ? 'Turn an evaluation in the list below back on, or create a new one, to see results here.'
                              : 'Create an evaluation to see results here.'}
                    </div>
                    <div className="flex flex-wrap justify-center gap-2">
                        {onlyPaused && (
                            <LemonButton
                                type="primary"
                                icon={<IconPlay />}
                                to={evaluationUrl(onlyPaused.id)}
                                data-attr="evaluation-overview-empty-resume"
                            >
                                Turn it back on
                            </LemonButton>
                        )}
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Evaluation}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type={onlyPaused ? 'secondary' : 'primary'}
                                icon={<IconPlus />}
                                to={urls.aiObservabilityEvaluationTemplates()}
                                data-attr="evaluation-overview-empty-create"
                            >
                                Create an evaluation
                            </LemonButton>
                        </AccessControlAction>
                    </div>
                </div>
            </div>
        </div>
    )
}
