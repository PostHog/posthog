import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useMemo, useRef } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'

import { booleanOutputConfigError, numericOutputConfigError } from '../constants'
import { evaluationSupportsReports } from '../evaluationCapabilities'
import { buildDeliveryTargets, evaluationReportLogic } from '../evaluationReportLogic'
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
                    <div className="flex flex-wrap items-center gap-2">
                        <h1 className="mb-0 text-2xl font-semibold">New evaluation</h1>
                        {template && <LemonTag type="muted">{`From the ${template.name} template`}</LemonTag>}
                    </div>
                </SceneStickyBar>
                <div className="w-full max-w-4xl mx-auto">
                    <EvaluationFormSteps checklist={checklist} onCreate={handleCreate} onCancel={handleCancel} />
                </div>
            </div>
        </BindLogic>
    )
}
