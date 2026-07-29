import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode, useState } from 'react'

import { IconCheck, IconGraph, IconPencil, IconPlay, IconRefresh, IconServer, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'
import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTextAreaMarkdown } from 'lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
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
import { InsightShortId } from '~/types'

import { humanizeDefinitionKind } from './common'
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
        updateMetric,
        loadRunResult,
        setEditingDefinition,
        setDraftMarkdown,
    } = useActions(dataCatalogMetricSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]

    if (metricLoading && !metric) {
        return <Spinner className="text-2xl" />
    }
    if (!metric) {
        return <NotFound object="metric" />
    }

    const sourceShortId = metric.source_insight_short_id
    const definitionSql = definitionField(metric, 'query')
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
            content: <div className="text-sm text-secondary">Deleting {metric.name} cannot be undone.</div>,
            primaryButton: { children: 'Delete', status: 'danger', onClick: deleteMetric },
            secondaryButton: { children: 'Cancel' },
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
        {
            key: 'run',
            label: 'Run metric',
            icon: <IconPlay />,
            onClick: loadRunResult,
            disabledReason: metric.definition_kind ? undefined : 'This metric has no runnable definition yet',
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
                    onNameChange={(value) => confirmAndUpdate({ display_name: value })}
                    onDescriptionChange={(value) => confirmAndUpdate({ description: value })}
                    renameDebounceMs={0}
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
                    onSaveMarkdown={(markdown) =>
                        confirmAndUpdate({ definition: { kind: 'MarkdownDefinition', markdown } })
                    }
                    onRun={loadRunResult}
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

function MetricDefinition({
    metric,
    editingDefinition,
    draftMarkdown,
    saving,
    runResult,
    runResultLoading,
    onDraftMarkdown,
    onEdit,
    onSaveMarkdown,
    onRun,
}: {
    metric: DataCatalogMetricApi
    editingDefinition: boolean
    draftMarkdown: string
    saving: boolean
    runResult: DataCatalogMetricRunResult | null
    runResultLoading: boolean
    onDraftMarkdown: (value: string) => void
    onEdit: (editing: boolean) => void
    onSaveMarkdown: (markdown: string) => void
    onRun: () => void
}): JSX.Element {
    const kind = metric.definition_kind
    const sql = definitionField(metric, 'query')

    const runButton = (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconPlay />}
            loading={runResultLoading}
            disabledReason={kind ? undefined : 'This metric has no runnable definition yet'}
            onClick={onRun}
        >
            Run metric
        </LemonButton>
    )
    const results = runResult ? <RunResult runResult={runResult} /> : null

    if (kind === 'HogQLQuery') {
        return (
            <Section title="Definition">
                <CodeSnippet language={Language.SQL}>{sql}</CodeSnippet>
                <div className="flex gap-2">
                    {runButton}
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconServer />}
                        to={urls.sqlEditor({ source: 'metric', metricName: metric.name })}
                    >
                        Open in SQL editor
                    </LemonButton>
                </div>
                {results}
            </Section>
        )
    }

    if (kind === 'MarkdownDefinition') {
        return (
            <Section title="Definition">
                {editingDefinition ? (
                    <>
                        <LemonTextAreaMarkdown value={draftMarkdown} onChange={onDraftMarkdown} />
                        <div className="flex gap-2">
                            <LemonButton
                                type="primary"
                                size="small"
                                loading={saving}
                                onClick={() => onSaveMarkdown(draftMarkdown)}
                            >
                                Save
                            </LemonButton>
                            <LemonButton type="secondary" size="small" onClick={() => onEdit(false)}>
                                Cancel
                            </LemonButton>
                        </div>
                    </>
                ) : (
                    <>
                        <LemonMarkdown disableImages>
                            {definitionField(metric, 'markdown') || '_No instructions yet._'}
                        </LemonMarkdown>
                        <div className="flex gap-2">
                            {runButton}
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPencil />}
                                onClick={() => onEdit(true)}
                            >
                                Edit
                            </LemonButton>
                        </div>
                        {results}
                    </>
                )}
            </Section>
        )
    }

    if (!kind) {
        return (
            <Section title="Definition">
                <LemonBanner type="info">
                    This metric is a stub with no definition. Add one to make it runnable.
                    <div className="flex gap-2 mt-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={urls.sqlEditor({ source: 'metric', metricName: metric.name })}
                        >
                            Write SQL
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            loading={saving}
                            onClick={() => onSaveMarkdown('1. Describe how to calculate this metric')}
                        >
                            Write markdown
                        </LemonButton>
                    </div>
                </LemonBanner>
            </Section>
        )
    }

    return (
        <Section title="Definition">
            <p className="text-secondary">
                This metric is derived from an insight. Edit the query in the insight, then refresh the metric.
            </p>
            <div className="flex gap-2">
                {runButton}
                {metric.source_insight_short_id && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconGraph />}
                        to={urls.insightView(metric.source_insight_short_id as InsightShortId)}
                    >
                        View source insight
                    </LemonButton>
                )}
            </div>
            {results}
        </Section>
    )
}

interface DataCatalogMetricRunResult {
    results?: unknown
    instructions?: string | null
    compiled_query?: string | null
}

function RunResult({ runResult }: { runResult: DataCatalogMetricRunResult }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {runResult.instructions ? (
                <LemonMarkdown disableImages>{runResult.instructions}</LemonMarkdown>
            ) : (
                <ResultsTable results={runResult.results} />
            )}
            {runResult.compiled_query && (
                <LemonCollapse
                    panels={[
                        {
                            key: 'compiled',
                            header: 'Compiled query',
                            content: <CodeSnippet language={Language.SQL}>{runResult.compiled_query}</CodeSnippet>,
                        },
                    ]}
                />
            )}
        </div>
    )
}

function ResultsTable({ results }: { results: unknown }): JSX.Element {
    const rows = Array.isArray(results) ? results : []
    if (rows.length === 0) {
        return <p className="text-secondary">No results.</p>
    }
    const first = rows[0]
    if (first && typeof first === 'object' && !Array.isArray(first)) {
        const keys = Object.keys(first as Record<string, unknown>)
        return (
            <LemonTable
                dataSource={rows as Record<string, unknown>[]}
                columns={keys.map((columnKey) => ({
                    title: columnKey,
                    key: columnKey,
                    render: (_: unknown, row: Record<string, unknown>) => formatCell(row[columnKey]),
                }))}
                size="small"
            />
        )
    }
    return <CodeSnippet language={Language.JSON}>{JSON.stringify(results, null, 2)}</CodeSnippet>
}

function formatCell(value: unknown): string {
    if (value == null) {
        return ''
    }
    return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function Section({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <h3 className="mb-0">{title}</h3>
            {children}
        </div>
    )
}
