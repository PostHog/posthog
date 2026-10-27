import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useMemo, useRef } from 'react'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { cn } from 'lib/utils/css-classes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneStickyBar, useSceneStickyBarBottom } from '~/layout/scenes/components/SceneStickyBar'

import { EvaluationCodeEditor } from '../components/EvaluationCodeEditor'
import { EvaluationPromptEditor } from '../components/EvaluationPromptEditor'
import { booleanOutputConfigError, numericOutputConfigError } from '../constants'
import { evaluationSupportsReports } from '../evaluationCapabilities'
import { evaluationReportLogic } from '../evaluationReportLogic'
import { evaluationSampleLogic } from '../evaluationSampleLogic'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { hasUnsetConditionRollout, llmEvaluationLogic } from '../llmEvaluationLogic'
import { defaultEvaluationTemplates } from '../templates'
import { categoryResultError, creationChecklist } from './creationChecklist'
import { EvaluationCreateButton } from './EvaluationCreateButton'
import { EvaluationNameFields } from './EvaluationNameFields'
import { EvaluationOutputFields } from './EvaluationOutputFields'
import { EvaluationResultPreview } from './EvaluationResultPreview'
import { EvaluationSamplePanel } from './EvaluationSamplePanel'
import { EvaluationSentence } from './EvaluationSentence'

/** The new evaluation form: its name, one sentence for the whole setup, and the instructions next to a real example. */
export function EvaluationCreatePage({ templateKey }: { templateKey?: string }): JSX.Element | null {
    const {
        evaluation,
        evaluationBackTarget,
        modelSelectionRequired,
        numericBoundsRequired,
        selectedModel,
        judgeModelGroups,
    } = useValues(llmEvaluationLogic)
    const { saveEvaluation, resetEvaluation } = useActions(llmEvaluationLogic)
    const { props: logicProps } = useMountedLogic(llmEvaluationLogic)
    const { volume } = useValues(evaluationVolumeLogic(logicProps))
    const template = defaultEvaluationTemplates.find((entry) => entry.key === templateKey)
    const headerRef = useRef<HTMLDivElement>(null)
    const headerBottom = useSceneStickyBarBottom(headerRef)

    const checklist = useMemo(() => {
        if (!evaluation) {
            return []
        }
        const resultError =
            evaluation.output_type === 'boolean'
                ? booleanOutputConfigError(evaluation.output_config)
                : evaluation.output_type === 'numeric'
                  ? numericOutputConfigError(evaluation.output_config, numericBoundsRequired)
                  : evaluation.output_type === 'categorical'
                    ? categoryResultError(evaluation.output_config)
                    : null
        return creationChecklist({
            evaluation,
            resultError: resultError ?? null,
            modelSelectionRequired,
            hasSelectedModel: !!selectedModel,
            hasAvailableModels: judgeModelGroups.some((group) => group.models.length > 0),
            hasUnsetSampling:
                evaluation.conditions.length === 0 ||
                hasUnsetConditionRollout(evaluation.conditions) ||
                evaluation.conditions.some((condition) => (condition.rollout_percentage ?? 0) > 100),
        })
    }, [evaluation, numericBoundsRequired, modelSelectionRequired, selectedModel, judgeModelGroups])

    if (!evaluation) {
        return null
    }

    const handleCreate = (): void => {
        const reportLogic = evaluationReportLogic({ evaluationId: 'new' })
        if (evaluationSupportsReports(evaluation) && reportLogic.isMounted() && reportLogic.values.configError) {
            lemonToast.error(reportLogic.values.configError)
            return
        }
        // pinned: analytics event name and properties, because the creation funnel reads them
        posthog.capture('llma evaluation create submitted', {
            evaluation_type: evaluation.evaluation_type,
            output_type: evaluation.output_type,
            target: evaluation.target,
            template_key: templateKey ?? 'blank',
            condition_sets: evaluation.conditions.length,
            has_filters: evaluation.conditions.some((condition) => (condition.properties ?? []).length > 0),
            start_running: evaluation.enabled,
            estimated_weekly_runs: volume?.runs ?? null,
        })
        saveEvaluation()
    }
    const handleCancel = (): void => {
        resetEvaluation()
        router.actions.push(evaluationBackTarget.path)
    }

    return (
        <BindLogic logic={evaluationVolumeLogic} props={logicProps}>
            <BindLogic logic={evaluationSampleLogic} props={logicProps}>
                <div className="@container/evaluation min-w-0 flex flex-col gap-4 pb-8">
                    <SceneBreadcrumbBackButton />
                    <SceneStickyBar
                        ref={headerRef}
                        hasSceneTitleSection={false}
                        className="flex flex-wrap items-center justify-between gap-2"
                    >
                        <div className="flex flex-wrap items-center gap-2">
                            <h1 className="mb-0 text-2xl font-semibold">New evaluation</h1>
                            {template && <LemonTag type="muted">{`From the ${template.name} template`}</LemonTag>}
                        </div>
                        {/* Narrow screens stack the summary under the form, so the actions also sit up here. */}
                        <div className="flex gap-2 @min-[64rem]/evaluation:hidden">
                            <LemonButton type="secondary" onClick={handleCancel}>
                                Cancel
                            </LemonButton>
                            <EvaluationCreateButton
                                onCreate={handleCreate}
                                disabledReason={checklist.find((item) => !item.done)?.todo}
                                data-attr="llma-evaluation-create-submit-top"
                            />
                        </div>
                    </SceneStickyBar>
                    {/* Fixed column widths keep the summary next to the form instead of drifting to the window's edge. */}
                    <div className="grid gap-4 grid-cols-1 @min-[64rem]/evaluation:grid-cols-[minmax(0,56rem)_18rem] items-start">
                        <div className="bg-bg-light border rounded p-4 @min-[40rem]/evaluation:p-6 min-w-0 flex flex-col gap-6">
                            <EvaluationNameFields />
                            <EvaluationSentence />
                            <div className="@container/instructions">
                                <div
                                    className={cn(
                                        'grid grid-cols-1 gap-6 items-start',
                                        // Sentiment has no instructions to write, so the example takes the whole row.
                                        evaluation.evaluation_type !== 'sentiment' &&
                                            '@min-[48rem]/instructions:grid-cols-2'
                                    )}
                                >
                                    <div className="flex flex-col gap-4 min-w-0">
                                        {evaluation.evaluation_type === 'llm_judge' && <EvaluationPromptEditor />}
                                        {evaluation.evaluation_type === 'hog' && <EvaluationCodeEditor />}
                                        <EvaluationOutputFields />
                                    </div>
                                    <EvaluationSamplePanel />
                                </div>
                            </div>
                        </div>
                        {/* Pinned just under the sticky header, so scrolling never hides the checklist behind it. */}
                        <div
                            className="@min-[64rem]/evaluation:sticky"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ top: headerBottom + 16 }}
                        >
                            <EvaluationResultPreview
                                checklist={checklist}
                                onCreate={handleCreate}
                                onCancel={handleCancel}
                            />
                        </div>
                    </div>
                </div>
            </BindLogic>
        </BindLogic>
    )
}
