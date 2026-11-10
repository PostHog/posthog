import { BindLogic, useActions, useValues } from 'kea'
import { ReactNode, useMemo, useState } from 'react'

import { LemonBanner, LemonButton, LemonDialog, LemonDivider, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelActionsSection, ScenePanelInfoSection } from '~/layout/scenes/SceneLayout'
import { useSceneAgentPanel } from '~/scenes/max/useSceneAgentPanel'
import { InsightShortId } from '~/types'

import { catalogRestructureEnabled } from 'products/data_modeling/frontend/catalogRestructure'

import { humanizeDefinitionKind, METRIC_DESCRIPTION_MAX_LENGTH, validateMetricName } from './common'
import { MetricDefinition } from './components/MetricDefinition'
import { MetricOwnerSelect } from './components/MetricOwnerSelect'
import { buildDataCatalogMetricAgentContext, DATA_CATALOG_METRIC_AGENT_HEADLINES } from './dataCatalogAgentContext'
import {
    dataCatalogMetricSceneLogic,
    DataCatalogMetricSceneLogicProps,
    MetricSceneTab,
} from './dataCatalogMetricSceneLogic'
import type { DataCatalogMetricApi } from './generated/api.schemas'
import { MetricLineageTab } from './MetricLineageTab'
import { buildMetricSceneActions, MAX_UNAVAILABLE_REASON } from './metricSceneActions'
import { QuillDataCatalogMetricScene } from './QuillDataCatalogMetricScene'
import { MetricTestsTab } from './tabs/MetricTestsTab'
import { MetricTestsTabLabel } from './tabs/MetricTestsTabLabel'

export const scene: SceneExport<DataCatalogMetricSceneLogicProps> = {
    component: DataCatalogMetricScene,
    logic: dataCatalogMetricSceneLogic,
    paramsToProps: ({ params: { name } }) => ({ name: name ?? '' }),
}

function tabPanelClassName(tab: MetricSceneTab, activeTab: MetricSceneTab): string {
    return tab === activeTab ? 'flex flex-col gap-y-4' : 'hidden'
}

export function DataCatalogMetricScene({ name }: DataCatalogMetricSceneLogicProps): JSX.Element {
    const { metric, editingDefinition, draftMarkdown } = useValues(dataCatalogMetricSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const contextItems = useMemo(
        () => buildDataCatalogMetricAgentContext(name, editingDefinition ? draftMarkdown : null),
        [draftMarkdown, editingDefinition, name]
    )

    useSceneAgentPanel({
        sceneKey: 'data-catalog',
        contextItems,
        headlines: DATA_CATALOG_METRIC_AGENT_HEADLINES,
        active: !!metric,
    })

    return catalogRestructureEnabled(featureFlags) ? (
        <QuillDataCatalogMetricScene name={name} />
    ) : (
        <LemonDataCatalogMetricScene name={name} />
    )
}

function LemonDataCatalogMetricScene({ name }: DataCatalogMetricSceneLogicProps): JSX.Element {
    const {
        metric,
        metricLoading,
        mutating,
        runResult,
        runResultLoading,
        editingDefinition,
        draftMarkdown,
        activeTab,
        mountedTabs,
    } = useValues(dataCatalogMetricSceneLogic)
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
        setActiveTab,
        runMetricWithAI,
    } = useActions(dataCatalogMetricSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]
    const { isMaxAvailable } = useValues(maxGlobalLogic)

    if (metricLoading && !metric) {
        return <MetricSceneSkeleton />
    }
    if (!metric) {
        return <NotFound object="metric" />
    }

    const sourceShortId = metric.source_insight_short_id
    const isApproved = metric.status === 'approved'

    const confirmAndUpdate = (patch: Partial<DataCatalogMetricApi>): void => {
        if (!isApproved) {
            updateMetric(patch)
            return
        }
        LemonDialog.open({
            title: 'Edit this approved metric?',
            content: (
                <div className="text-sm text-secondary">
                    Saving this change sets the metric back to proposed. Approve it again now, or leave it for a
                    teammate to review.
                </div>
            ),
            primaryButton: {
                children: 'Save and approve',
                onClick: () => updateMetric(patch, true),
                disabledReason: metric.is_drifted
                    ? 'This metric has drifted from its source insight. Refresh it before approving.'
                    : undefined,
                'data-attr': 'data-catalog-metric-save-and-approve',
            },
            secondaryButton: {
                children: 'Save and reset to proposed',
                onClick: () => updateMetric(patch),
                'data-attr': 'data-catalog-metric-save-and-reset',
            },
            tertiaryButton: { children: 'Cancel' },
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
                    <LemonField name="name" label="SQL name">
                        <LemonInput data-attr="data-catalog-metric-rename-input" autoFocus />
                    </LemonField>
                </div>
            ),
            errors: { name: (value) => validateMetricName(value ?? '') },
            onSubmit: ({ name: newName }) => renameMetric(newName),
        })
    }

    const actions = buildMetricSceneActions({
        metric,
        mutating,
        running: runResultLoading,
        biModeEnabled: !!featureFlags[FEATURE_FLAGS.SQL_EDITOR_BI_MODE],
        isMaxAvailable,
        handlers: {
            approve: approveMetric,
            refreshFromInsight: refreshMetricFromInsight,
            run: loadRunResult,
            runWithAI: runMetricWithAI,
            rename: openRenameDialog,
            delete: confirmDelete,
        },
    })

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

                <LemonTabs
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    tabs={[
                        { key: 'definition', label: 'Definition' },
                        { key: 'lineage', label: 'Lineage' },
                        {
                            key: 'data-quality',
                            label: <MetricTestsTabLabel metricId={metric.id} />,
                        },
                    ]}
                />

                {mountedTabs.includes('definition') && (
                    <div className={tabPanelClassName('definition', activeTab)}>
                        <MetricMetadata
                            metric={metric}
                            saving={mutating}
                            onSaveUnit={(unit) => confirmAndUpdate({ unit })}
                            onSaveOwner={(owner) => updateMetric({ owner })}
                        />

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
                            onRunWithAI={runMetricWithAI}
                            runWithAIDisabledReason={isMaxAvailable ? undefined : MAX_UNAVAILABLE_REASON}
                        />
                    </div>
                )}

                {mountedTabs.includes('lineage') && (
                    <div className={tabPanelClassName('lineage', activeTab)}>
                        <MetricLineageTab metric={metric} />
                    </div>
                )}

                {mountedTabs.includes('data-quality') && (
                    <div className={tabPanelClassName('data-quality', activeTab)}>
                        <MetricTestsTab />
                    </div>
                )}
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

function MetricSceneSkeleton(): JSX.Element {
    return (
        <SceneContent>
            <LemonSkeleton className="h-8 w-80" />
            <LemonSkeleton className="h-4 w-1/2" />
            <LemonSkeleton className="h-9 w-72" />
            <div className="grid grid-cols-2 gap-x-8 gap-y-3 max-w-2xl">
                <LemonSkeleton className="h-10" repeat={4} />
            </div>
            <LemonSkeleton className="h-64 w-full" />
        </SceneContent>
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
    saving,
    onSaveUnit,
    onSaveOwner,
}: {
    metric: DataCatalogMetricApi
    saving: boolean
    onSaveUnit: (unit: string) => void
    onSaveOwner: (owner: string | null) => void
}): JSX.Element {
    const showProvenance = metric.created_source === 'ai_generated'

    return (
        <div className="flex flex-col gap-3">
            <StatusRow metric={metric} />
            <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm max-w-2xl">
                <MetadataItem
                    label="Owner"
                    value={<MetricOwnerSelect owner={metric.owner} loading={saving} onChange={onSaveOwner} />}
                />
                <MetadataItem label="Approved by" value={metric.approved_by?.email || 'Not approved'} />
                <MetadataItem
                    label="Approved at"
                    value={metric.approved_at ? <TZLabel time={metric.approved_at} /> : 'Not approved'}
                />
                <MetadataItem
                    label="Last run"
                    value={metric.last_run_at ? <TZLabel time={metric.last_run_at} /> : 'Never'}
                />
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
