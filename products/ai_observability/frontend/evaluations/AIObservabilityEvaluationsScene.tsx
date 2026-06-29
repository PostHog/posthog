import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconCopy, IconPencil, IconPlus, IconSearch, IconTrash, IconWarning } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonSwitch,
    LemonTab,
    LemonTable,
    LemonTabs,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LLMProviderKey } from '../settings/llmProviderKeysLogic'
import {
    getUnhealthyProviderKey,
    providerKeyStateIssueDescription,
    providerKeyStateLabel,
    providerLabel,
} from '../settings/providerKeyStateUtils'
import { TrialUsageMeter } from '../settings/TrialUsageMeter'
import {
    EvaluationMetrics,
    PASS_RATE_SUCCESS_THRESHOLD,
    PASS_RATE_WARNING_THRESHOLD,
} from './components/EvaluationMetrics'
import { OfflineEvaluationsTab } from './components/OfflineEvaluationsTab'
import { evaluationTypeCanBeCreated, evaluationTypeUsesProviderKey } from './evaluationCapabilities'
import { EvaluationStats, evaluationMetricsLogic } from './evaluationMetricsLogic'
import { EvaluationTemplatesEmptyState } from './EvaluationTemplates'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'
import { statusReasonLabel } from './statusDisplay'
import { EvaluationConfig } from './types'

export const scene: SceneExport = {
    component: AIObservabilityEvaluationsScene,
    logic: llmEvaluationsLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
}

function getActiveTab(
    pathname: string,
    searchParams: Record<string, unknown>,
    showOfflineEvals: boolean
): 'online-evals' | 'offline-evals' {
    if (!showOfflineEvals) {
        return 'online-evals'
    }

    const normalizedPathname = removeProjectIdIfPresent(pathname)
    const offlineEvaluationsPath = urls.aiObservabilityOfflineEvaluations()
    if (normalizedPathname === offlineEvaluationsPath || normalizedPathname.startsWith(`${offlineEvaluationsPath}/`)) {
        return 'offline-evals'
    }

    const tab = searchParams.tab
    return tab === 'offline-evals' || tab === 'offline' ? 'offline-evals' : 'online-evals'
}

function getProviderKeyIssue(evaluation: EvaluationConfig, providerKeys: LLMProviderKey[]): LLMProviderKey | null {
    if (!evaluationTypeUsesProviderKey(evaluation.evaluation_type)) {
        return null
    }

    return getUnhealthyProviderKey(providerKeys, evaluation.model_configuration?.provider_key_id)
}

function getEvaluationMethodLabel(evaluation: EvaluationConfig): string {
    if (evaluation.evaluation_type === 'hog') {
        return 'Hog'
    }
    if (evaluation.evaluation_type === 'sentiment') {
        return 'Sentiment'
    }
    return 'LLM judge'
}

function getEvaluationMethodTagType(evaluation: EvaluationConfig): 'option' | 'highlight' | 'caution' {
    if (evaluation.evaluation_type === 'hog') {
        return 'option'
    }
    if (evaluation.evaluation_type === 'sentiment') {
        return 'highlight'
    }
    return 'caution'
}

function getEvaluationConfigPreview(evaluation: EvaluationConfig): string {
    if (evaluation.evaluation_type === 'hog') {
        return evaluation.evaluation_config.source
    }
    if (evaluation.evaluation_type === 'sentiment') {
        return 'User messages'
    }
    return evaluation.evaluation_config.prompt
}

function AIObservabilityEvaluationsContent(): JSX.Element {
    const evaluationsLogic = llmEvaluationsLogic()
    const metricsLogic = evaluationMetricsLogic()
    const {
        evaluations,
        filteredEvaluations,
        evaluationsLoading,
        evaluationsFilter,
        dateFilter,
        providerKeys,
        unhealthyProviderKeysUsedByEvaluations,
        canEnableEvaluation,
    } = useValues(evaluationsLogic)
    const { setEvaluationsFilter, toggleEvaluationEnabled, duplicateEvaluation, loadEvaluations, setDates } =
        useActions(evaluationsLogic)
    const { evaluationsWithMetrics } = useValues(metricsLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { push } = useActions(router)
    const { searchParams } = useValues(router)
    const evaluationUrl = (id: string): string => combineUrl(urls.aiObservabilityEvaluation(id), searchParams).url
    const settingsUrl = urls.settings('project-ai-observability', 'ai-observability-byok')

    const filteredEvaluationsWithMetrics = evaluationsWithMetrics.filter((evaluation: EvaluationConfig) =>
        filteredEvaluations.some((filtered) => filtered.id === evaluation.id)
    )

    if (!evaluationsLoading && evaluations.length === 0) {
        return <EvaluationTemplatesEmptyState />
    }

    const columns: LemonTableColumns<EvaluationConfig> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, evaluation) => (
                <div className="flex flex-col">
                    <Link to={evaluationUrl(evaluation.id)} className="font-semibold text-primary">
                        {evaluation.name}
                    </Link>
                    {evaluation.description && <div className="text-muted text-sm">{evaluation.description}</div>}
                </div>
            ),
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, evaluation) => {
                // When the system has marked an eval as errored, the toggle is misleading — flipping it
                // would just fail. Show an error pill instead so the row is visibly different and users
                // click through to the detail page to see what's wrong and how to fix it.
                if (evaluation.status === 'error') {
                    return (
                        <Tooltip title={`${statusReasonLabel(evaluation.status_reason)}. Open to fix.`}>
                            <LemonTag type="danger" icon={<IconWarning />} data-attr="evaluation-status-error">
                                Error
                            </LemonTag>
                        </Tooltip>
                    )
                }
                const providerKeyIssue = evaluation.enabled ? getProviderKeyIssue(evaluation, providerKeys) : null
                if (providerKeyIssue) {
                    return (
                        <Tooltip
                            title={`Paused because API key ${providerKeyIssue.name} ${providerKeyStateIssueDescription(
                                providerKeyIssue.state
                            )}.`}
                        >
                            <LemonTag type="warning" icon={<IconWarning />} data-attr="evaluation-status-key-issue">
                                Key issue
                            </LemonTag>
                        </Tooltip>
                    )
                }
                const canUseEvaluationType = evaluationTypeCanBeCreated(evaluation.evaluation_type, featureFlags)
                const canEnable = canEnableEvaluation(evaluation) && (evaluation.enabled || canUseEvaluationType)
                const isBlocked = !canEnable && !evaluation.enabled
                const blockedReason = !canUseEvaluationType
                    ? 'Sentiment evaluations are not available for this project.'
                    : 'Trial evaluation limit reached. Add a provider API key to re-enable.'
                return (
                    <div className="flex items-center gap-2">
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <Tooltip title={isBlocked ? blockedReason : undefined}>
                                <span>
                                    <LemonSwitch
                                        checked={evaluation.enabled}
                                        onChange={() => toggleEvaluationEnabled(evaluation.id)}
                                        size="small"
                                        disabled={isBlocked}
                                        data-attr="toggle-evaluation-enabled"
                                    />
                                </span>
                            </Tooltip>
                        </AccessControlAction>
                        <span className={evaluation.enabled ? 'text-success' : 'text-muted'}>
                            {evaluation.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                    </div>
                )
            },
            // Sort: errors first (most attention-demanding), then enabled, then paused.
            sorter: (a, b) => {
                const rank = (e: EvaluationConfig): number => (e.status === 'error' ? 0 : e.enabled ? 1 : 2)
                return rank(a) - rank(b)
            },
        },
        {
            title: 'Method',
            key: 'method',
            render: (_, evaluation) => (
                <LemonTag type={getEvaluationMethodTagType(evaluation)}>
                    {getEvaluationMethodLabel(evaluation)}
                </LemonTag>
            ),
        },
        {
            title: 'Config',
            key: 'config',
            render: (_, evaluation) => {
                const preview = getEvaluationConfigPreview(evaluation)
                return (
                    <div className="max-w-md">
                        <div className="text-sm font-mono bg-bg-light border rounded px-2 py-1 truncate">
                            {preview || '(empty)'}
                        </div>
                    </div>
                )
            },
        },
        {
            title: 'Triggers',
            key: 'conditions',
            render: (_, evaluation) => (
                <div className="flex flex-wrap gap-1">
                    {evaluation.conditions.map((condition) => {
                        const propertyCount = condition.properties?.length ?? 0
                        return (
                            <LemonTag key={condition.id} type="option">
                                {parseFloat((condition.rollout_percentage ?? 0).toFixed(2))}%
                                {propertyCount > 0 &&
                                    ` when ${propertyCount} condition${propertyCount !== 1 ? 's' : ''}`}
                            </LemonTag>
                        )
                    })}
                    {evaluation.conditions.length === 0 && <span className="text-muted text-sm">No triggers</span>}
                </div>
            ),
        },
        {
            title: 'Runs',
            key: 'recent_stats',
            render: (_, evaluation: EvaluationConfig & { stats?: EvaluationStats }) => {
                const stats = evaluation.stats
                if (!stats || stats.runs_count === 0) {
                    return <span className="text-muted text-sm">No runs</span>
                }

                // Sentiment evals classify rather than pass/fail, so a pass rate is meaningless
                if (evaluation.evaluation_type === 'sentiment') {
                    return (
                        <div className="text-sm">
                            {stats.runs_count} run{stats.runs_count !== 1 ? 's' : ''}
                        </div>
                    )
                }

                const passRateColor =
                    stats.pass_rate >= PASS_RATE_SUCCESS_THRESHOLD
                        ? 'text-success'
                        : stats.pass_rate >= PASS_RATE_WARNING_THRESHOLD
                          ? 'text-warning'
                          : 'text-danger'

                return (
                    <div className="flex flex-col items-center">
                        <div className="text-sm">
                            {stats.runs_count} run{stats.runs_count !== 1 ? 's' : ''}
                        </div>
                        <div className={`font-semibold ${passRateColor}`}>
                            {parseFloat(stats.pass_rate.toFixed(2))}%
                        </div>
                    </div>
                )
            },
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_, evaluation) => (
                <div className="flex gap-1">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPencil />}
                            onClick={() => push(evaluationUrl(evaluation.id))}
                        />
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconCopy />}
                            onClick={() => duplicateEvaluation(evaluation.id)}
                        />
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            status="danger"
                            icon={<IconTrash />}
                            onClick={() => {
                                LemonDialog.open({
                                    title: `Delete ${evaluation.name}?`,
                                    description: 'Are you sure you want to delete this evaluation?',
                                    primaryButton: {
                                        children: 'Delete',
                                        type: 'primary',
                                        status: 'danger',
                                        'data-attr': 'confirm-delete-evaluation',
                                        onClick: () => {
                                            deleteWithUndo({
                                                endpoint: `environments/${currentTeamId}/evaluations`,
                                                object: evaluation,
                                                callback: () => loadEvaluations(),
                                            })
                                        },
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                        type: 'secondary',
                                    },
                                })
                            }}
                        />
                    </AccessControlAction>
                </div>
            ),
        },
    ]

    return (
        <div className="space-y-4">
            <TrialUsageMeter showSettingsLink={false} />

            {unhealthyProviderKeysUsedByEvaluations.length > 0 && (
                <LemonBanner type="warning">
                    <div className="space-y-2">
                        <p>Some evaluations are using API keys that need attention.</p>
                        <ul className="list-disc pl-5 space-y-1">
                            {unhealthyProviderKeysUsedByEvaluations.map((providerKey) => (
                                <li key={providerKey.id}>
                                    <span className="font-semibold">{providerKey.name}</span> (
                                    {providerLabel(providerKey.provider)}) - {providerKeyStateLabel(providerKey.state)}:{' '}
                                    {providerKey.error_message || 'Unknown error'}
                                </li>
                            ))}
                        </ul>
                        <Link to={settingsUrl}>Go to settings to fix API keys.</Link>
                    </div>
                </LemonBanner>
            )}

            <LemonBanner type="info" dismissKey="evals-billing-notice">
                Each evaluation run counts as an AI observability event.
            </LemonBanner>

            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-xl font-semibold">Online evals</h2>
                    <p className="text-muted">
                        Configure evaluation prompts and triggers to automatically assess your AI generations.
                    </p>
                </div>
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        to={combineUrl(urls.aiObservabilityEvaluationTemplates(), searchParams).url}
                        data-attr="create-evaluation-button"
                        tooltip="Create evaluation"
                    >
                        Create evaluation
                    </LemonButton>
                </AccessControlAction>
            </div>

            <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />

            <EvaluationMetrics />

            <div className="flex items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search online evals..."
                    value={evaluationsFilter}
                    data-attr="evaluations-search-input"
                    onChange={setEvaluationsFilter}
                    prefix={<IconSearch />}
                    className="max-w-sm"
                />
            </div>

            <LemonTable
                columns={columns}
                dataSource={filteredEvaluationsWithMetrics}
                loading={evaluationsLoading}
                rowKey="id"
                pagination={{
                    pageSize: 50,
                }}
                nouns={['evaluation', 'evaluations']}
            />
        </div>
    )
}

export function AIObservabilityEvaluationsScene(): JSX.Element {
    const { searchParams, location } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const evaluationsLogic = useMountedLogic(llmEvaluationsLogic())
    const metricsLogic = evaluationMetricsLogic()
    const showOfflineEvals = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_OFFLINE_EVALS]
    const activeTab = getActiveTab(location.pathname, searchParams, showOfflineEvals)

    useAttachedLogic(metricsLogic, evaluationsLogic)

    const tabs: LemonTab<string>[] = [
        {
            key: 'online-evals',
            label: 'Online evals',
            content: <AIObservabilityEvaluationsContent />,
            link: combineUrl(urls.aiObservabilityEvaluations(), {
                ...searchParams,
                tab: undefined,
                experiment: undefined,
            }).url,
            'data-attr': 'evaluations-tab',
        },
        ...(showOfflineEvals
            ? [
                  {
                      key: 'offline-evals',
                      label: (
                          <span className="inline-flex items-center gap-1">
                              <span>Offline evals</span>
                              <LemonTag type="completion" size="small">
                                  Alpha
                              </LemonTag>
                          </span>
                      ),
                      content: <OfflineEvaluationsTab />,
                      link: combineUrl(urls.aiObservabilityOfflineEvaluations(), {
                          ...searchParams,
                          tab: undefined,
                          experiment: undefined,
                      }).url,
                      'data-attr': 'offline-evals-tab',
                  } as LemonTab<string>,
              ]
            : []),
        {
            key: 'settings',
            label: 'Settings',
            link: urls.settings('project-ai-observability', 'ai-observability-byok'),
            content: <></>,
            'data-attr': 'settings-tab',
        },
    ]

    return (
        <BindLogic logic={llmEvaluationsLogic} props={{}}>
            <BindLogic logic={evaluationMetricsLogic} props={{}}>
                <SceneContent>
                    <SceneTitleSection
                        name="Evaluations"
                        description="Configure and monitor automated LLM output evaluations."
                        resourceType={{
                            type: 'llm_evaluations',
                        }}
                        actions={
                            <LemonButton
                                to="https://posthog.com/docs/ai-evals/evaluations"
                                type="secondary"
                                targetBlank
                                size="small"
                            >
                                Documentation
                            </LemonButton>
                        }
                    />
                    <LemonTabs activeKey={activeTab} data-attr="evaluations-tabs" tabs={tabs} sceneInset />
                </SceneContent>
            </BindLogic>
        </BindLogic>
    )
}
