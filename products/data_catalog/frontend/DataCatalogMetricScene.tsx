import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode, useState } from 'react'

import {
    IconCheck,
    IconGraph,
    IconPencil,
    IconPlay,
    IconRefresh,
    IconServer,
    IconSparkles,
    IconTrash,
} from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { autoRunMaxPrompt } from 'scenes/max/maxPrompt'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelActionsSection, ScenePanelInfoSection } from '~/layout/scenes/SceneLayout'
import { InsightShortId, SidePanelTab } from '~/types'

import { humanizeDefinitionKind, METRIC_DESCRIPTION_MAX_LENGTH, validateMetricName } from './common'
import { MetricDefinition } from './components/MetricDefinition'
import { buildMetricRunPrompt } from './components/RunMetricWithAIButton'
import {
    dataCatalogMetricSceneLogic,
    DataCatalogMetricSceneLogicProps,
    definitionField,
} from './dataCatalogMetricSceneLogic'
import type { DataCatalogMetricApi } from './generated/api.schemas'

export const scene: SceneExport<DataCatalogMetricSceneLogicProps> = {
    component: DataCatalogMetricScene,
    logic: dataCatalogMetricSceneLogic,
    paramsToProps: ({ params: { name } }) => ({ name: name ?? '' }),
}

interface MetricAction {
    key: string
    label: string
    icon: JSX.Element
    onClick: () => void
    disabledReason?: string
    destructive?: boolean
    opensFloatingUi?: boolean
}

const DRIFT_APPROVE_DISABLED = 'This metric has drifted from its source insight. Refresh it first.'

export function DataCatalogMetricScene({ name }: DataCatalogMetricSceneLogicProps): JSX.Element {
    const { metric, metricLoading, mutating, runResult, runResultLoading, editingDefinition, draftMarkdown } =
        useValues(dataCatalogMetricSceneLogic)
    const {
        approveMetric,
        refreshMetricFromInsight,
        deleteMetric,
        renameMetric,
        updateMetric,
        loadRunResult,
        setEditingDefinition,
        setDraftMarkdown,
        startEditingMarkdown,
    } = useActions(dataCatalogMetricSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { isMaxAvailable } = useValues(maxGlobalLogic)

    const runMarkdownMetricWithAI = (): void => {
        if (!metric) {
            return
        }
        // Still record the run server-side so last run time and run analytics stay accurate.
        loadRunResult()
        openSidePanel(SidePanelTab.Max, autoRunMaxPrompt(buildMetricRunPrompt(metric.name)))
    }

    if (metricLoading && !metric) {
        return <Spinner className="text-2xl" />
    }
    if (!metric) {
        return <NotFound object="metric" />
    }

    const sourceShortId = metric.source_insight_short_id
    const definitionSql = definitionField(metric, 'query')
    const isApproved = metric.status === 'approved'
    const isMarkdownMetric = metric.definition_kind === 'MarkdownDefinition'

    const confirmAndUpdate = (patch: Partial<DataCatalogMetricApi>): void => {
        if (!isApproved) {
            updateMetric(patch)
            return
        }
        LemonDialog.open({
            title: 'Edit this approved metric?',
            content: (
                <div className="text-sm text-secondary">
                    Saving this change sets the metric back to proposed, so it will need to be approved again.
                </div>
            ),
            primaryButton: { children: 'Save and reset to proposed', onClick: () => updateMetric(patch) },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const confirmDelete = (): void => {
        LemonDialog.open({
            title: 'Delete metric?',
            content: (
                <div className="text-sm text-secondary">
                    This deletes {metric.name} and makes its name available for a new metric. Queries and links that
                    reference it will stop working.
                </div>
            ),
            primaryButton: { children: 'Delete', status: 'danger', onClick: deleteMetric },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const openRenameDialog = (): void => {
        LemonDialog.openForm({
            title: 'Rename metric',
            initialValues: { name: metric.name },
            content: (
                <div className="flex flex-col gap-2">
                    <div className="text-sm text-secondary">
                        Anything that references this metric by name, like saved SQL queries, API calls, or links, will
                        stop working until it is updated. The old name becomes available for a new metric.
                        {isApproved && ' Renaming also sets the metric back to proposed, so it needs approving again.'}
                    </div>
                    <LemonField name="name" label="Name">
                        <LemonInput data-attr="data-catalog-metric-rename-input" autoFocus />
                    </LemonField>
                </div>
            ),
            errors: { name: (value) => validateMetricName(value ?? '') },
            onSubmit: ({ name: newName }) => renameMetric(newName),
        })
    }

    const actions: MetricAction[] = [
        ...(isApproved
            ? []
            : [
                  {
                      key: 'approve',
                      label: 'Approve',
                      icon: <IconCheck />,
                      onClick: approveMetric,
                      disabledReason: metric.is_drifted ? DRIFT_APPROVE_DISABLED : mutating ? 'Working' : undefined,
                  },
              ]),
        ...(sourceShortId
            ? [
                  {
                      key: 'refresh',
                      label: 'Refresh from insight',
                      icon: <IconRefresh />,
                      onClick: refreshMetricFromInsight,
                      disabledReason: mutating ? 'Working' : undefined,
                  },
                  {
                      key: 'source-insight',
                      label: 'View source insight',
                      icon: <IconGraph />,
                      onClick: () => router.actions.push(urls.insightView(sourceShortId as InsightShortId)),
                  },
              ]
            : []),
        isMarkdownMetric
            ? {
                  key: 'run',
                  label: 'Run with AI',
                  icon: <IconSparkles />,
                  onClick: runMarkdownMetricWithAI,
                  disabledReason: isMaxAvailable ? undefined : 'PostHog AI is not available on this instance',
              }
            : {
                  key: 'run',
                  label: 'Run metric',
                  icon: <IconPlay />,
                  onClick: loadRunResult,
                  disabledReason: metric.definition_kind ? undefined : 'This metric has no runnable definition yet',
              },
        {
            key: 'rename',
            label: 'Rename',
            icon: <IconPencil />,
            onClick: openRenameDialog,
            disabledReason: mutating ? 'Working' : undefined,
            opensFloatingUi: true,
        },
        ...(definitionSql
            ? [
                  {
                      key: 'open-sql',
                      label: 'Open in SQL editor',
                      icon: <IconServer />,
                      onClick: () => router.actions.push(urls.sqlEditor({ source: 'metric', metricName: metric.name })),
                  },
              ]
            : []),
        {
            key: 'delete',
            label: 'Delete',
            icon: <IconTrash />,
            onClick: confirmDelete,
            destructive: true,
            opensFloatingUi: true,
        },
    ]

    const nonDestructive = actions.filter((action) => !action.destructive)
    const destructive = actions.filter((action) => action.destructive)

    return (
        <BindLogic logic={dataCatalogMetricSceneLogic} props={{ name }}>
            <SceneContent>
                {sceneMenuBarEnabled && (
                    <SceneMenuBar>
                        <SceneMenuBarMenu label="Metric" dataAttr="data-catalog-metric-menubar">
                            {nonDestructive.map((action) => (
                                <SceneMenuBarItem
                                    key={action.key}
                                    onClick={action.onClick}
                                    disabled={!!action.disabledReason}
                                    data-attr={`data-catalog-metric-menubar-${action.key}`}
                                >
                                    {action.icon}
                                    {action.label}
                                </SceneMenuBarItem>
                            ))}
                            <SceneMenuBarSeparator />
                            {destructive.map((action) => (
                                <SceneMenuBarItem
                                    key={action.key}
                                    variant="destructive"
                                    onClick={action.onClick}
                                    data-attr={`data-catalog-metric-menubar-${action.key}`}
                                >
                                    {action.icon}
                                    {action.label}
                                </SceneMenuBarItem>
                            ))}
                        </SceneMenuBarMenu>
                    </SceneMenuBar>
                )}

                <SceneTitleSection
                    name={metric.display_name || metric.name}
                    description={metric.description}
                    resourceType={{ type: 'data_warehouse' }}
                    canEdit
                    onNameChange={(value) => updateMetric({ display_name: value })}
                    onDescriptionChange={(value) => confirmAndUpdate({ description: value })}
                    descriptionMaxLength={METRIC_DESCRIPTION_MAX_LENGTH}
                    renameDebounceMs={0}
                    saveOnBlur
                />

                {metric.is_drifted && (
                    <LemonBanner type="warning">
                        This metric has drifted from its source insight, so it cannot be approved. Refresh it from the
                        insight to pick up the current query.
                        <div className="flex gap-2 mt-2">
                            {sourceShortId && (
                                <LemonButton type="secondary" size="small" onClick={refreshMetricFromInsight}>
                                    Refresh from insight
                                </LemonButton>
                            )}
                            {sourceShortId && (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    to={urls.insightView(sourceShortId as InsightShortId)}
                                >
                                    View source insight
                                </LemonButton>
                            )}
                        </div>
                    </LemonBanner>
                )}

                {!isApproved && !metric.is_drifted && (
                    <LemonBanner type="info">
                        This metric is proposed. Approve it once the definition looks right.
                        <div className="flex gap-2 mt-2">
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={approveMetric}
                                disabledReason={mutating ? 'Working' : undefined}
                            >
                                Approve metric
                            </LemonButton>
                        </div>
                    </LemonBanner>
                )}

                <MetricMetadata metric={metric} onSaveUnit={(unit) => confirmAndUpdate({ unit })} />

                <MetricDefinition
                    metric={metric}
                    editingDefinition={editingDefinition}
                    draftMarkdown={draftMarkdown}
                    saving={mutating}
                    runResult={runResult}
                    runResultLoading={runResultLoading}
                    onDraftMarkdown={setDraftMarkdown}
                    onEdit={setEditingDefinition}
                    onStartEditingMarkdown={startEditingMarkdown}
                    onSaveMarkdown={(markdown) =>
                        confirmAndUpdate({ definition: { kind: 'MarkdownDefinition', markdown } })
                    }
                    onRun={loadRunResult}
                    onRunWithAI={runMarkdownMetricWithAI}
                    runWithAIDisabledReason={
                        isMaxAvailable ? undefined : 'PostHog AI is not available on this instance'
                    }
                />
            </SceneContent>

            <ScenePanel>
                <ScenePanelInfoSection>
                    <div className="flex flex-col gap-1 text-sm">
                        <StatusRow metric={metric} />
                    </div>
                </ScenePanelInfoSection>
                <ScenePanelActionsSection>
                    {nonDestructive.map((action) => (
                        <ButtonPrimitive
                            key={action.key}
                            menuItem
                            onClick={action.onClick}
                            disabled={!!action.disabledReason}
                            tooltip={action.disabledReason}
                        >
                            {action.icon}
                            {action.label}
                        </ButtonPrimitive>
                    ))}
                    <LemonDivider />
                    {destructive.map((action) => (
                        <ButtonPrimitive key={action.key} menuItem onClick={action.onClick} className="text-danger">
                            {action.icon}
                            {action.label}
                        </ButtonPrimitive>
                    ))}
                </ScenePanelActionsSection>
            </ScenePanel>
        </BindLogic>
    )
}

function StatusRow({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            <LemonTag type={metric.status === 'approved' ? 'success' : 'warning'}>{metric.status}</LemonTag>
            {metric.is_drifted && <LemonTag type="danger">Drifted</LemonTag>}
            <LemonTag type="option">{humanizeDefinitionKind(metric.definition_kind)}</LemonTag>
        </div>
    )
}

function MetricMetadata({
    metric,
    onSaveUnit,
}: {
    metric: DataCatalogMetricApi
    onSaveUnit: (unit: string) => void
}): JSX.Element {
    const referencedTables = Array.isArray(metric.referenced_table_names)
        ? (metric.referenced_table_names as string[])
        : []
    const showProvenance = metric.created_source === 'ai_generated'

    return (
        <div className="flex flex-col gap-3">
            <StatusRow metric={metric} />
            <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm max-w-2xl">
                <MetadataItem label="Owner" value={metric.owner || 'Unassigned'} />
                <MetadataItem label="Approved by" value={metric.approved_by?.email || 'Not approved'} />
                <MetadataItem
                    label="Approved at"
                    value={metric.approved_at ? <TZLabel time={metric.approved_at} /> : 'Not approved'}
                />
                <MetadataItem
                    label="Last run"
                    value={metric.last_run_at ? <TZLabel time={metric.last_run_at} /> : 'Never'}
                />
                {referencedTables.length > 0 && (
                    <div className="flex flex-col gap-1">
                        <span className="text-secondary">Referenced tables</span>
                        <div className="flex flex-wrap gap-1">
                            {referencedTables.map((table) => (
                                <LemonTag key={table} type="option">
                                    {table}
                                </LemonTag>
                            ))}
                        </div>
                    </div>
                )}
            </div>
            {showProvenance && (
                <LemonCollapse
                    panels={[
                        {
                            key: 'provenance',
                            header: 'AI provenance',
                            content: (
                                <div className="flex flex-col gap-1 text-sm">
                                    {metric.ai_model && <span>Model: {metric.ai_model}</span>}
                                    {metric.confidence != null && (
                                        <span>Confidence: {Math.round(metric.confidence * 100)}%</span>
                                    )}
                                    {metric.reasoning && <span>{metric.reasoning}</span>}
                                </div>
                            ),
                        },
                    ]}
                />
            )}
            <UnitEditor key={metric.unit || ''} unit={metric.unit || ''} onSave={onSaveUnit} />
        </div>
    )
}

function MetadataItem({ label, value }: { label: string; value: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col">
            <span className="text-secondary">{label}</span>
            <span>{value}</span>
        </div>
    )
}

function UnitEditor({ unit, onSave }: { unit: string; onSave: (unit: string) => void }): JSX.Element {
    const [value, setValue] = useState(unit)
    return (
        <LemonField.Pure label="Unit" info="How the result is measured, like users, dollars, or percent.">
            <div className="flex items-center gap-2 max-w-md">
                <LemonInput value={value} onChange={setValue} placeholder="users" />
                <LemonButton
                    type="secondary"
                    size="small"
                    disabledReason={value === unit ? 'No changes to save' : undefined}
                    onClick={() => onSave(value)}
                >
                    Save
                </LemonButton>
            </div>
        </LemonField.Pure>
    )
}
