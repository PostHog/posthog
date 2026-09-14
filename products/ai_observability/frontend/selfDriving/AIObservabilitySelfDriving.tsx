import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import type { ReactNode } from 'react'

import { IconCalendar, IconPlus, IconQuestion, IconUser, IconWarning } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonCollapse,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { MCPUseCaseCard } from 'lib/components/MCPHint/MCPUseCaseCard'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import type { LemonCollapsePanel } from 'lib/lemon-ui/LemonCollapse'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import type { AlertApi } from 'products/alerts/frontend/generated/api.schemas'
import {
    ScoutCreateModalHost,
    useScoutCreateDisabledReason,
} from 'products/signals/frontend/inbox/components/config/scouts/ScoutCreateModalHost'
import { ScoutSummaryRow } from 'products/signals/frontend/inbox/components/config/scouts/ScoutSummaryRow'
import { scoutFleetLogic } from 'products/signals/frontend/inbox/logics/scoutFleetLogic'
import { signalSourcesLogic } from 'products/signals/frontend/inbox/signalSourcesLogic'

import { llmEvaluationsLogic } from '../evaluations/llmEvaluationsLogic'
import type { EvaluationConfig } from '../evaluations/types'
import type { EvaluationReportApi } from '../generated/api.schemas'
import {
    AI_OBSERVABILITY_SCOUT_TEMPLATES,
    AIObservabilityScoutTemplate,
    findAIObservabilityScoutTemplate,
    isAIObservabilityScout,
} from './aiObservabilityScoutTemplates'
import {
    AI_OBSERVABILITY_SELF_DRIVING_SECTIONS,
    type AIObservabilitySelfDrivingSection,
    aiObservabilitySelfDrivingLogic,
} from './aiObservabilitySelfDrivingLogic'
import { SelfDrivingSignalSourceToggle } from './SelfDrivingSignalSourceToggle'

const SCOUTS_DOCS_URL = 'https://posthog.com/docs/ai-observability/self-driving'
const SELF_DRIVING_DOCS_URL = 'https://posthog.com/docs/self-driving'
const SIGNALS_DOCS_URL = `${SELF_DRIVING_DOCS_URL}/signals`
const EVAL_REPORTS_DOCS_URL = `${SCOUTS_DOCS_URL}#eval-reports`
const ANOMALY_INVESTIGATIONS_DOCS_URL = `${SCOUTS_DOCS_URL}#anomaly-investigations`

function evaluationEditUrl(evaluationId: string): string {
    return combineUrl(urls.aiObservabilityEvaluation(evaluationId), {
        evaluation_tab: 'configuration',
    }).url
}

function sectionPanel({
    key,
    dataAttr,
    title,
    count,
    content,
}: {
    key: AIObservabilitySelfDrivingSection
    dataAttr: string
    title: string
    count: number | null
    content: ReactNode
}): LemonCollapsePanel<AIObservabilitySelfDrivingSection> {
    return {
        key,
        dataAttr,
        bodyClassName: '!border-t-0',
        header: {
            className: '!bg-transparent hover:!bg-surface-secondary',
            children: (
                <div className="flex w-full items-center gap-2">
                    <span className="text-base font-semibold">{title}</span>
                    {count !== null ? (
                        <LemonTag type="muted" size="small">
                            {count}
                        </LemonTag>
                    ) : null}
                </div>
            ),
        },
        content,
    }
}

const anomalyAlertColumns: LemonTableColumns<AlertApi> = [
    {
        title: 'Alert',
        key: 'name',
        width: '30%',
        render: (_, alert) => <span className="font-semibold">{alert.name || 'Untitled alert'}</span>,
        sorter: (left, right) => (left.name || '').localeCompare(right.name || ''),
    },
    {
        title: 'Insight',
        key: 'insight',
        width: '30%',
        render: (_, alert) => (
            <Link to={urls.insightView(alert.insight_short_id as InsightShortId)}>{alert.insight_display_name}</Link>
        ),
        sorter: (left, right) => left.insight_display_name.localeCompare(right.insight_display_name),
    },
    {
        title: 'Agent investigation',
        key: 'agent-investigation',
        render: (_, alert) =>
            alert.investigation_agent_enabled ? (
                <LemonTag type="success">Enabled</LemonTag>
            ) : (
                <LemonTag type="muted">Disabled</LemonTag>
            ),
        sorter: (left, right) =>
            Number(Boolean(left.investigation_agent_enabled)) - Number(Boolean(right.investigation_agent_enabled)),
    },
    {
        title: 'Last checked',
        key: 'last-checked',
        render: (_, alert) => (alert.last_checked_at ? <TZLabel time={alert.last_checked_at} /> : 'Never'),
        sorter: (left, right) => {
            const leftTime = left.last_checked_at ? dayjs(left.last_checked_at).valueOf() : Infinity
            const rightTime = right.last_checked_at ? dayjs(right.last_checked_at).valueOf() : Infinity
            return leftTime - rightTime
        },
    },
    {
        key: 'actions',
        width: 72,
        align: 'right',
        render: (_, alert) => (
            <LemonButton
                type="secondary"
                size="small"
                to={urls.alert(alert.id)}
                targetBlank
                hideExternalLinkIcon
                data-attr="edit-anomaly-alert"
            >
                Edit
            </LemonButton>
        ),
    },
]

const TEMPLATE_ICONS: Record<AIObservabilityScoutTemplate['key'], JSX.Element> = {
    'daily-digest': <IconCalendar />,
    'costly-users': <IconUser />,
    'error-patterns': <IconWarning />,
}

/**
 * The one create modal for this tab, so a card click and a `#template=` link land in the same
 * place. Hosted beside the cards rather than inside one, since the URL can open it for any of them.
 */
function ScoutTemplateModal(): JSX.Element | null {
    const { openScoutTemplateKey } = useValues(aiObservabilitySelfDrivingLogic)
    const { setOpenScoutTemplateKey } = useActions(aiObservabilitySelfDrivingLogic)
    const { loadScoutConfigs } = useActions(scoutFleetLogic)

    return (
        <ScoutCreateModalHost
            initialValues={findAIObservabilityScoutTemplate(openScoutTemplateKey)?.initialValues ?? null}
            onClose={() => setOpenScoutTemplateKey(null)}
            onCreated={() => loadScoutConfigs()}
        />
    )
}

function ScoutTemplateCard({ template }: { template: AIObservabilityScoutTemplate }): JSX.Element {
    const { setOpenScoutTemplateKey } = useActions(aiObservabilitySelfDrivingLogic)
    const creationDisabledReason = useScoutCreateDisabledReason()

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
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    disabledReason={creationDisabledReason ?? undefined}
                    onClick={() => setOpenScoutTemplateKey(template.key)}
                    data-attr={`create-${template.key}-scout`}
                >
                    Use template
                </LemonButton>
            </div>
        </LemonCard>
    )
}

export function AIObservabilitySelfDriving(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { scoutConfigs, scoutConfigsLoading, updatingScoutIds } = useValues(scoutFleetLogic)
    const { loadScoutConfigs, updateScoutConfig } = useActions(scoutFleetLogic)
    const { evaluations, evaluationsLoadFailed, evaluationsLoading } = useValues(llmEvaluationsLogic)
    const { loadEvaluations } = useActions(llmEvaluationsLogic)
    const {
        anomalyAlertInvestigations,
        anomalyAlertInvestigationsLoading,
        evaluationReportsByEvaluationId,
        evaluationReportsLoading,
        expandedSections,
    } = useValues(aiObservabilitySelfDrivingLogic)
    const { loadAnomalyAlertInvestigations, loadSelfDrivingEvaluationReports, setExpandedSections } = useActions(
        aiObservabilitySelfDrivingLogic
    )
    const {
        anomalyInvestigationConfig,
        evalReportsConfig,
        isAnomalyInvestigationToggling,
        isEvalReportsToggling,
        sourceConfigs,
        sourceConfigsLoadFailed,
    } = useValues(signalSourcesLogic)
    const { loadSourceConfigs, toggleAnomalyInvestigation, toggleEvalReports } = useActions(signalSourcesLogic)

    const aiObservabilityScouts = scoutConfigs?.filter(isAIObservabilityScout) ?? []
    const reportFor = (evaluation: EvaluationConfig): EvaluationReportApi | null =>
        evaluationReportsByEvaluationId?.[evaluation.id] ?? null
    const evaluationColumns: LemonTableColumns<EvaluationConfig> = [
        {
            title: 'Name',
            key: 'name',
            width: '40%',
            sorter: (a, b) => a.name.localeCompare(b.name),
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
            sorter: (a, b) => Number(reportFor(a)?.enabled ?? false) - Number(reportFor(b)?.enabled ?? false),
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
            sorter: (a, b) => (reportFor(a)?.generated_report_count ?? 0) - (reportFor(b)?.generated_report_count ?? 0),
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
            // Never-generated evals sort as the oldest rather than mixing into the middle of the list.
            sorter: (a, b) =>
                dayjs(reportFor(a)?.last_generated_at ?? 0).valueOf() -
                dayjs(reportFor(b)?.last_generated_at ?? 0).valueOf(),
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
                    targetBlank
                    hideExternalLinkIcon
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
                    <ScoutSummaryRow
                        key={config.id}
                        config={config}
                        onUpdate={updateScoutConfig}
                        updating={updatingScoutIds.includes(config.id)}
                    />
                ))}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            {/* Outside the collapse: a `#template=` link has to work even with Scouts collapsed. */}
            <ScoutTemplateModal />
            <LemonBanner type="info" className="text-sm">
                <p className="m-0">
                    To power{' '}
                    <Link to={SELF_DRIVING_DOCS_URL} target="_blank" targetBlankIcon>
                        Self-driving
                    </Link>
                    , AI Observability turns your LLM data into{' '}
                    <Link to={SIGNALS_DOCS_URL} target="_blank" targetBlankIcon>
                        signals
                    </Link>
                    : agents investigate what changed, and reports land in your{' '}
                    <Link to={urls.inbox()} target="_blank" targetBlankIcon>
                        inbox
                    </Link>
                    , where one click turns a finding into a pull request.{' '}
                    <Link to={SCOUTS_DOCS_URL} target="_blank" targetBlankIcon>
                        Learn more
                    </Link>
                </p>
            </LemonBanner>
            <LemonCollapse
                embedded
                multiple
                activeKeys={expandedSections}
                onChange={setExpandedSections}
                panels={[
                    sectionPanel({
                        key: AI_OBSERVABILITY_SELF_DRIVING_SECTIONS.SCOUTS,
                        dataAttr: 'ai-observability-scouts-collapse',
                        title: 'Scouts',
                        count: scoutConfigs !== null ? aiObservabilityScouts.length : null,
                        content: (
                            <div className="flex flex-col gap-6">
                                <section className="flex flex-col gap-2">
                                    <div>
                                        <div className="flex items-center gap-2">
                                            <h2 className="m-0 text-base font-semibold">Start with a template</h2>
                                            <Tooltip
                                                title="Each template is a pre-defined scout: a scheduled agent that explores your AI observability data and surfaces findings worth reviewing. Actionable scout reports land in your inbox."
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
                                        <h2 className="m-0 text-base font-semibold">Your AI observability scouts</h2>
                                        <p className="m-0 text-sm text-muted">
                                            Add the <code>ai-observability</code> label to a scout for it to appear
                                            here.
                                        </p>
                                    </div>
                                    {scoutsContent}
                                </section>
                            </div>
                        ),
                    }),
                    sectionPanel({
                        key: AI_OBSERVABILITY_SELF_DRIVING_SECTIONS.EVAL_REPORTS,
                        dataAttr: 'ai-observability-eval-reports-collapse',
                        title: 'Eval reports',
                        count: !evaluationsLoading && !evaluationsLoadFailed ? evaluations.length : null,
                        content: (
                            <div className="flex flex-col gap-2">
                                <p className="m-0 text-sm text-muted">
                                    Signals from evals are only generated if eval reports are enabled.{' '}
                                    <Link to={EVAL_REPORTS_DOCS_URL} target="_blank" targetBlankIcon>
                                        Learn more
                                    </Link>
                                </p>
                                <SelfDrivingSignalSourceToggle
                                    sourceName="AI observability"
                                    signalNoun="evaluation report"
                                    enabled={sourceConfigs === null ? null : !!evalReportsConfig?.enabled}
                                    loadFailed={sourceConfigsLoadFailed}
                                    toggling={isEvalReportsToggling}
                                    onChange={toggleEvalReports}
                                    onRetry={loadSourceConfigs}
                                    data-attr="self-driving-eval-reports-signal-source"
                                />
                                {!evaluationsLoadFailed &&
                                !evaluationsLoading &&
                                evaluations.length > 0 &&
                                evaluationReportsByEvaluationId === null &&
                                !evaluationReportsLoading ? (
                                    <LemonBanner
                                        type="error"
                                        action={{
                                            children: 'Try again',
                                            onClick: () => loadSelfDrivingEvaluationReports(),
                                        }}
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
                                    <LemonCard
                                        hoverEffect={false}
                                        className="flex w-full flex-col items-start gap-3 p-4"
                                    >
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
                                                if (
                                                    (event.target as HTMLElement).closest('button, a, [role="button"]')
                                                ) {
                                                    return
                                                }
                                                newInternalTab(evaluationEditUrl(evaluation.id))
                                            },
                                        })}
                                    />
                                )}
                            </div>
                        ),
                    }),
                    sectionPanel({
                        key: AI_OBSERVABILITY_SELF_DRIVING_SECTIONS.ANOMALY_ALERT_INVESTIGATIONS,
                        dataAttr: 'ai-observability-anomaly-investigations-collapse',
                        title: 'Anomaly alert investigations',
                        count: anomalyAlertInvestigations !== null ? anomalyAlertInvestigations.length : null,
                        content: (
                            <div className="flex flex-col gap-2">
                                <p className="m-0 text-sm text-muted">
                                    Insights with anomaly detection alerts that have agent investigation enabled can
                                    emit signals. Add the <code>ai-observability</code> tag to an{' '}
                                    <Link to={urls.savedInsights()} target="_blank" targetBlankIcon>
                                        insight
                                    </Link>{' '}
                                    to show its anomaly alerts here.{' '}
                                    <Link to={ANOMALY_INVESTIGATIONS_DOCS_URL} target="_blank" targetBlankIcon>
                                        Learn more
                                    </Link>
                                </p>
                                <SelfDrivingSignalSourceToggle
                                    sourceName="Product analytics"
                                    signalNoun="anomaly investigation"
                                    enabled={sourceConfigs === null ? null : !!anomalyInvestigationConfig?.enabled}
                                    loadFailed={sourceConfigsLoadFailed}
                                    toggling={isAnomalyInvestigationToggling}
                                    onChange={toggleAnomalyInvestigation}
                                    onRetry={loadSourceConfigs}
                                    data-attr="self-driving-anomaly-investigation-signal-source"
                                />
                                {anomalyAlertInvestigationsLoading && anomalyAlertInvestigations === null ? (
                                    <div className="flex flex-col gap-2">
                                        <LemonSkeleton className="h-10 w-full rounded" />
                                        <LemonSkeleton className="h-10 w-full rounded" />
                                    </div>
                                ) : anomalyAlertInvestigations === null ? (
                                    <LemonBanner
                                        type="error"
                                        action={{
                                            children: 'Try again',
                                            onClick: () => loadAnomalyAlertInvestigations(),
                                        }}
                                        data-attr="anomaly-alert-investigations-load-error"
                                    >
                                        We couldn't load anomaly alert investigations. Try again in a moment.
                                    </LemonBanner>
                                ) : anomalyAlertInvestigations.length === 0 ? (
                                    <LemonCard
                                        hoverEffect={false}
                                        className="flex flex-col gap-1 p-4 text-sm text-muted"
                                    >
                                        <p className="m-0">
                                            No anomaly alerts match this view. Add the <code>ai-observability</code> tag
                                            to an{' '}
                                            <Link to={urls.savedInsights()} target="_blank" targetBlankIcon>
                                                insight
                                            </Link>{' '}
                                            with an anomaly alert for it to appear here.
                                        </p>
                                        <p className="m-0">
                                            A good place to start is your{' '}
                                            <Link to={urls.aiObservabilityDashboard()} target="_blank" targetBlankIcon>
                                                AI observability dashboard
                                            </Link>
                                            .
                                        </p>
                                    </LemonCard>
                                ) : (
                                    <LemonTable
                                        columns={anomalyAlertColumns}
                                        dataSource={anomalyAlertInvestigations}
                                        tableLayout="fixed"
                                        rowKey="id"
                                        rowClassName="[&>td]:py-2 [&>td_.LemonButton]:my-0"
                                        nouns={['anomaly alert', 'anomaly alerts']}
                                        data-attr="anomaly-alert-investigations-table"
                                        onRow={(alert) => ({
                                            className: 'cursor-pointer hover:bg-surface-secondary',
                                            onClick: (event) => {
                                                if (
                                                    (event.target as HTMLElement).closest('button, a, [role="button"]')
                                                ) {
                                                    return
                                                }
                                                newInternalTab(urls.alert(alert.id))
                                            },
                                        })}
                                    />
                                )}
                            </div>
                        ),
                    }),
                ]}
            />
        </div>
    )
}
