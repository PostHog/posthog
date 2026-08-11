import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconCalendar, IconQuestion, IconUser, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { MCPUseCaseCard } from 'lib/components/MCPHint/MCPUseCaseCard'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { ScoutCreateButton } from 'products/signals/frontend/inbox/components/config/scouts/ScoutCreateButton'
import { ScoutRowCard } from 'products/signals/frontend/inbox/components/config/scouts/ScoutRowCard'
import { scoutFleetLogic } from 'products/signals/frontend/inbox/logics/scoutFleetLogic'

import { llmEvaluationsLogic } from '../evaluations/llmEvaluationsLogic'
import type { EvaluationConfig } from '../evaluations/types'
import {
    AI_OBSERVABILITY_SCOUT_TEMPLATES,
    AIObservabilityScoutTemplate,
    isAIObservabilityScout,
} from './aiObservabilityScoutTemplates'
import { aiObservabilitySelfDrivingLogic } from './aiObservabilitySelfDrivingLogic'

const SCOUTS_DOCS_URL = 'https://posthog.com/docs/ai-observability/self-driving'
const EVAL_REPORTS_DOCS_URL = `${SCOUTS_DOCS_URL}#eval-reports`

function evaluationEditUrl(evaluationId: string): string {
    return combineUrl(urls.aiObservabilityEvaluation(evaluationId), {
        evaluation_tab: 'configuration',
    }).url
}

const TEMPLATE_ICONS: Record<AIObservabilityScoutTemplate['key'], JSX.Element> = {
    'daily-digest': <IconCalendar />,
    'costly-users': <IconUser />,
    'error-patterns': <IconWarning />,
}

function ScoutTemplateCard({ template }: { template: AIObservabilityScoutTemplate }): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-3">
            <div className="flex min-w-0 items-start gap-2">
                <span className="mt-0.5 shrink-0 text-muted">{TEMPLATE_ICONS[template.key]}</span>
                <div className="min-w-0">
                    <h3 className="m-0 text-sm font-semibold">{template.title}</h3>
                    <p className="m-0 text-xs text-muted">{template.description}</p>
                </div>
            </div>
            <div className="mt-auto flex items-center justify-between gap-2">
                <LemonTag type="muted" size="small">
                    {template.schedule}
                </LemonTag>
                <ScoutCreateButton
                    initialValues={template.initialValues}
                    onCreated={() => loadScoutConfigs()}
                    data-attr={`create-${template.key}-scout`}
                >
                    Use template
                </ScoutCreateButton>
            </div>
        </LemonCard>
    )
}

export function AIObservabilitySelfDriving(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { scoutConfigs, scoutConfigsLoading, deletingScoutIds, updatingScoutIds } = useValues(scoutFleetLogic)
    const { deleteScout, loadScoutConfigs, updateScoutConfig } = useActions(scoutFleetLogic)
    const { evaluations, evaluationsLoadFailed, evaluationsLoading } = useValues(llmEvaluationsLogic)
    const { loadEvaluations } = useActions(llmEvaluationsLogic)
    const { evaluationReportsByEvaluationId, evaluationReportsLoading } = useValues(aiObservabilitySelfDrivingLogic)
    const { loadSelfDrivingEvaluationReports } = useActions(aiObservabilitySelfDrivingLogic)

    const aiObservabilityScouts = scoutConfigs?.filter(isAIObservabilityScout) ?? []
    const evaluationColumns: LemonTableColumns<EvaluationConfig> = [
        {
            title: 'Name',
            key: 'name',
            width: '40%',
            render: (_, evaluation) => (
                <div className="flex min-w-0 flex-col">
                    <span className="truncate font-semibold">{evaluation.name}</span>
                    <span className="min-h-4 truncate text-xs text-muted">{evaluation.description ?? ''}</span>
                </div>
            ),
        },
        {
            title: 'Eval reports',
            key: 'reports',
            render: (_, evaluation) => {
                if (evaluationReportsByEvaluationId === null) {
                    return <LemonTag type="muted">Unavailable</LemonTag>
                }

                return evaluationReportsByEvaluationId[evaluation.id]?.enabled ? (
                    <LemonTag type="success">Enabled</LemonTag>
                ) : (
                    <LemonTag type="muted">Disabled</LemonTag>
                )
            },
        },
        {
            title: 'Reports generated',
            key: 'generated_report_count',
            render: (_, evaluation) => {
                if (evaluationReportsByEvaluationId === null) {
                    return 'Unavailable'
                }

                return evaluationReportsByEvaluationId[evaluation.id]?.generated_report_count ?? 0
            },
        },
        {
            title: 'Last generated',
            key: 'last_generated_at',
            render: (_, evaluation) => {
                if (evaluationReportsByEvaluationId === null) {
                    return 'Unavailable'
                }

                const lastGeneratedAt = evaluationReportsByEvaluationId[evaluation.id]?.last_generated_at
                return lastGeneratedAt ? <TZLabel time={lastGeneratedAt} /> : 'Never'
            },
        },
        {
            key: 'actions',
            width: 72,
            align: 'right',
            render: (_, evaluation) => (
                <LemonButton
                    type="secondary"
                    size="small"
                    to={evaluationEditUrl(evaluation.id)}
                    data-attr="edit-ai-observability-evaluation"
                >
                    Edit
                </LemonButton>
            ),
        },
    ]

    let scoutsContent: JSX.Element
    if (scoutConfigsLoading && scoutConfigs === null) {
        scoutsContent = (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-16 w-full rounded" />
                <LemonSkeleton className="h-16 w-full rounded" />
            </div>
        )
    } else if (scoutConfigs === null) {
        scoutsContent = (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadScoutConfigs() }}
                data-attr="ai-observability-scouts-load-error"
            >
                We couldn't load your AI observability scouts. Try again in a moment.
            </LemonBanner>
        )
    } else if (aiObservabilityScouts.length === 0) {
        scoutsContent = (
            <LemonCard hoverEffect={false} className="p-4 text-sm text-muted">
                No AI observability scouts yet. Use a template above to create one.
            </LemonCard>
        )
    } else {
        scoutsContent = (
            <div className="flex flex-col gap-2">
                {aiObservabilityScouts.map((config) => (
                    <ScoutRowCard
                        key={config.id}
                        config={config}
                        rollup={undefined}
                        onUpdate={updateScoutConfig}
                        onDelete={deleteScout}
                        deleting={deletingScoutIds.includes(config.id)}
                        updating={updatingScoutIds.includes(config.id)}
                    />
                ))}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-6">
            <section className="flex flex-col gap-2">
                <div>
                    <div className="flex items-center gap-2">
                        <h2 className="m-0 text-base font-semibold">Start with a template</h2>
                        <Tooltip
                            title="Each template is a pre-defined scout – a scheduled agent that explores your AI observability data and surfaces findings worth reviewing. Actionable scout reports land in your inbox."
                            docLink={SCOUTS_DOCS_URL}
                        >
                            <span
                                className="inline-flex items-center gap-1 text-xs text-muted hover:text-default cursor-pointer transition-colors"
                                data-attr="ai-observability-scout-templates-what-is-this"
                            >
                                <IconQuestion className="text-sm" />
                                What is this?
                            </span>
                        </Tooltip>
                    </div>
                    <p className="m-0 text-sm text-muted">
                        Choose a starting point, then review and edit it before saving.
                    </p>
                </div>
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {AI_OBSERVABILITY_SCOUT_TEMPLATES.map((template) => (
                        <ScoutTemplateCard key={template.key} template={template} />
                    ))}
                </div>
            </section>

            <section className="flex flex-col gap-2">
                <div>
                    <div className="flex items-center gap-2">
                        <h2 className="m-0 text-base font-semibold">Your AI observability scouts</h2>
                        {scoutConfigs !== null ? (
                            <LemonTag type="muted" size="small">
                                {aiObservabilityScouts.length}
                            </LemonTag>
                        ) : null}
                    </div>
                    <p className="m-0 text-sm text-muted">
                        Add the <code>ai-observability</code> label to a scout for it to appear here.
                    </p>
                </div>
                {scoutsContent}
            </section>

            <section className="flex flex-col gap-2">
                <div>
                    <div className="flex items-center gap-2">
                        <h2 className="m-0 text-base font-semibold">Your evals</h2>
                        {!evaluationsLoading && !evaluationsLoadFailed ? (
                            <LemonTag type="muted" size="small">
                                {evaluations.length}
                            </LemonTag>
                        ) : null}
                    </div>
                    <p className="m-0 text-sm text-muted">
                        Signals from evals are only generated if eval reports are enabled.{' '}
                        <Link to={EVAL_REPORTS_DOCS_URL} target="_blank" targetBlankIcon>
                            Learn more
                        </Link>
                    </p>
                </div>
                {!evaluationsLoadFailed &&
                !evaluationsLoading &&
                evaluations.length > 0 &&
                evaluationReportsByEvaluationId === null &&
                !evaluationReportsLoading ? (
                    <LemonBanner
                        type="error"
                        action={{ children: 'Try again', onClick: () => loadSelfDrivingEvaluationReports() }}
                        data-attr="ai-observability-evaluation-reports-load-error"
                    >
                        We couldn't load evaluation report statuses. Try again in a moment.
                    </LemonBanner>
                ) : null}
                {evaluationsLoadFailed ? (
                    <LemonBanner
                        type="error"
                        action={{ children: 'Try again', onClick: loadEvaluations }}
                        data-attr="ai-observability-evaluations-load-error"
                    >
                        We couldn't load your evals. Try again in a moment.
                    </LemonBanner>
                ) : evaluationsLoading ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-10 w-full rounded" />
                        <LemonSkeleton className="h-10 w-full rounded" />
                    </div>
                ) : evaluations.length === 0 ? (
                    <LemonCard hoverEffect={false} className="flex w-full flex-col items-start gap-3 p-4">
                        <h3 className="m-0 text-sm font-semibold">You don't have any evals yet</h3>
                        <LemonButton
                            type="primary"
                            to={urls.aiObservabilityEvaluations()}
                            data-attr="create-ai-observability-eval"
                        >
                            Create an eval
                        </LemonButton>
                        {featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI] ? (
                            <MCPUseCaseCard
                                surfaceKey="ai_observability_evaluations.create"
                                className="!mt-1 w-full max-w-2xl"
                            />
                        ) : null}
                    </LemonCard>
                ) : (
                    <LemonTable
                        columns={evaluationColumns}
                        dataSource={evaluations}
                        loading={evaluationReportsLoading}
                        loadingSkeletonRows={2}
                        tableLayout="fixed"
                        rowKey="id"
                        nouns={['eval', 'evals']}
                        data-attr="ai-observability-evaluations-table"
                        onRow={(evaluation) => ({
                            className: 'cursor-pointer hover:bg-surface-secondary',
                            onClick: (event) => {
                                if ((event.target as HTMLElement).closest('button, a, [role="button"]')) {
                                    return
                                }
                                router.actions.push(evaluationEditUrl(evaluation.id))
                            },
                        })}
                    />
                )}
            </section>
        </div>
    )
}
