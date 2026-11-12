import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useMemo, useRef } from 'react'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'

import { booleanOutputConfigError, numericOutputConfigError } from '../constants'
import { evaluationSupportsReports } from '../evaluationCapabilities'
import { evaluationPreviewLogic } from '../evaluationPreviewLogic'
import { buildDeliveryTargets, evaluationReportLogic } from '../evaluationReportLogic'
import { matchesNoUnits } from '../evaluationVolume'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { hasUnsetConditionRollout, llmEvaluationLogic } from '../llmEvaluationLogic'
import { defaultEvaluationTemplates } from '../templates'
import { categoryResultError, creationChecklist } from './creationChecklist'
import { EvaluationFormSteps } from './EvaluationFormSteps'

/** The new evaluation form: centered steps under a sentence that sums up the setup. */
export function EvaluationCreatePage({ templateKey }: { templateKey?: string }): JSX.Element | null {
    const {
        evaluation,
        evaluationBackTarget,
        modelSelectionRequired,
        numericBoundsRequired,
        usesDecisionModel,
        selectedModel,
        judgeModelGroups,
        isReportableEvaluation,
    } = useValues(llmEvaluationLogic)
    const { saveEvaluation, resetEvaluation } = useActions(llmEvaluationLogic)
    const { props: logicProps } = useMountedLogic(llmEvaluationLogic)
    const { volume } = useValues(evaluationVolumeLogic(logicProps))
    const { codeError, everyTestErrored } = useValues(evaluationPreviewLogic(logicProps))
    const template = defaultEvaluationTemplates.find((entry) => entry.key === templateKey)
    const headerRef = useRef<HTMLDivElement>(null)

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
            codeError,
            everyTestErrored,
            wouldNotRun: matchesNoUnits(volume)
                ? `No matching generation has a ${evaluation.target} ID, so it would not run`
                : null,
        })
    }, [
        evaluation,
        numericBoundsRequired,
        modelSelectionRequired,
        selectedModel,
        judgeModelGroups,
        codeError,
        everyTestErrored,
        volume,
    ])

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
            uses_decision_model: usesDecisionModel,
            reports_enabled: reportLogic.isMounted()
                ? reportLogic.values.configDraft.enabled && isReportableEvaluation
                : null,
            report_frequency: reportLogic.isMounted() ? reportLogic.values.configDraft.frequency : null,
            report_destinations: reportLogic.isMounted()
                ? buildDeliveryTargets(reportLogic.values.configDraft).length
                : null,
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
            <div className="@container/evaluation min-w-0 flex flex-col gap-4 pb-8">
                <SceneBreadcrumbBackButton />
                <SceneStickyBar
                    ref={headerRef}
                    hasSceneTitleSection={false}
                    className="flex flex-wrap items-center justify-between gap-2"
                >
                    <h1 className="mb-0 text-2xl font-semibold">
                        {template ? `New ${template.name.toLowerCase()} evaluation` : 'New evaluation'}
                    </h1>
                </SceneStickyBar>
                <div className="w-full max-w-6xl mx-auto">
                    <EvaluationFormSteps checklist={checklist} onCreate={handleCreate} onCancel={handleCancel} />
                </div>
            </div>
        </BindLogic>
    )
}
