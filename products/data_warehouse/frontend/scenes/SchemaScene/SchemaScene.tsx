import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { DataQualityChecksPanel } from 'products/data_quality/frontend/DataQualityChecksPanel'
import { cleanSourceId } from 'products/data_warehouse/frontend/utils'

import { shouldShowManagedSourceMetricsTab, shouldShowManagedSourceSyncsTab } from '../SourceScene/SourceScene'
import { SyncsTab } from '../SourceScene/tabs/SyncsTab'
import { ConfigurationTab } from './ConfigurationTab'
import { MetricsTab } from './MetricsTab'
import {
    SCHEMA_CONFIGURATION_SECTIONS,
    SchemaConfigurationSection,
    SchemaSceneProps,
    SchemaSceneTab,
    schemaSceneLogic,
} from './schemaSceneLogic'

export type { SchemaConfigurationSection, SchemaSceneTab } from './schemaSceneLogic'

export const scene: SceneExport<SchemaSceneProps> = {
    component: SchemaScene,
    logic: schemaSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE,
    paramsToProps: ({ params: { sourceId, schemaId } }) => ({ sourceId, schemaId }),
}

const SECTION_LABELS: Record<SchemaConfigurationSection, string> = {
    details: 'Details',
    'sync-method': 'Sync method',
    columns: 'Columns and filters',
    descriptions: 'Descriptions',
    schedule: 'Schedule',
    'danger-zone': 'Danger zone',
}

export function SchemaScene({ sourceId, schemaId }: SchemaSceneProps): JSX.Element {
    if (!sourceId || !schemaId) {
        return <NotFound object="Data warehouse schema" />
    }

    return <SchemaSceneContent sourceId={sourceId} schemaId={schemaId} />
}

function SchemaSceneContent({ sourceId, schemaId }: SchemaSceneProps): JSX.Element {
    const { currentTab, currentSection, schema, source, schemaDataLoading, supportsColumnSelection } = useValues(
        schemaSceneLogic({ sourceId, schemaId })
    )
    const { setCurrentTab, setCurrentSection } = useActions(schemaSceneLogic({ sourceId, schemaId }))
    const { featureFlags } = useValues(featureFlagLogic)

    const cleanedSourceId = cleanSourceId(sourceId)
    const showSyncs = shouldShowManagedSourceSyncsTab(source)
    const showMetrics = shouldShowManagedSourceMetricsTab(source, !!featureFlags[FEATURE_FLAGS.DWH_SOURCE_METRICS])
    const showDescriptions = !!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SEMANTIC_ENRICHMENT]
    // The warehouse table only exists once the schema has synced, and checks hang off that table.
    const showDataQuality = !!featureFlags[FEATURE_FLAGS.DATA_QUALITY_CHECKS] && !!schema?.table?.id
    const showColumnsSection = supportsColumnSelection
    const visibleSections = SCHEMA_CONFIGURATION_SECTIONS.filter(
        (key) => (key !== 'columns' || showColumnsSection) && (key !== 'descriptions' || showDescriptions)
    )

    useEffect(() => {
        // Wait for the source before deciding a tab is unavailable. While it's null `showSyncs` and
        // `showMetrics` are false, so a URL-selected "syncs" tab would get bounced to Configuration
        // and push a bogus history entry over the URL the user actually navigated to.
        if (!source) {
            return
        }
        if (!showSyncs && currentTab === 'syncs') {
            setCurrentTab('configuration')
        }
        if (!showMetrics && currentTab === 'metrics') {
            setCurrentTab('configuration')
        }
    }, [source, showSyncs, showMetrics, currentTab, setCurrentTab])

    useEffect(() => {
        // Wait for the schema, for the same reason the tab check above waits for the source.
        if (schema && !showDataQuality && currentTab === 'data-quality') {
            setCurrentTab('configuration')
        }
    }, [schema, showDataQuality, currentTab, setCurrentTab])

    useEffect(() => {
        if (!showColumnsSection && currentSection === 'columns') {
            setCurrentSection('details')
        }
    }, [showColumnsSection, currentSection, setCurrentSection])

    useEffect(() => {
        if (!showDescriptions && currentSection === 'descriptions') {
            setCurrentSection('details')
        }
    }, [showDescriptions, currentSection, setCurrentSection])

    if (schemaDataLoading && !schema) {
        return (
            <SceneContent>
                <LemonSkeleton className="w-full h-12" />
                <LemonSkeleton className="w-full h-96" />
            </SceneContent>
        )
    }

    if (!schema) {
        return <NotFound object="Data warehouse schema" />
    }

    const tabs: LemonTab<SchemaSceneTab>[] = [
        {
            label: 'Configuration',
            key: 'configuration',
            content: (
                <ConfigurationSectionLayout
                    sections={visibleSections}
                    section={currentSection}
                    onSectionChange={setCurrentSection}
                    body={
                        <ConfigurationTab
                            sourceId={cleanedSourceId}
                            schema={schema}
                            source={source}
                            section={currentSection}
                            onConfigureSyncMethod={() => setCurrentSection('sync-method')}
                            syncHistoryUrl={
                                showSyncs ? urls.dataWarehouseSourceSchema(sourceId, schema.id, 'syncs') : undefined
                            }
                        />
                    }
                />
            ),
        },
    ]

    if (showSyncs) {
        tabs.push({
            label: 'Syncs',
            key: 'syncs',
            content: (
                <div className="flex flex-col gap-2">
                    <div className="flex justify-end">
                        <LemonButton type="secondary" size="small" to={urls.dataWarehouseSource(sourceId, 'syncs')}>
                            View all syncs for source
                        </LemonButton>
                    </div>
                    <SyncsTab id={cleanedSourceId} lockedSchema={schema.name} />
                </div>
            ),
        })
    }

    if (showMetrics) {
        tabs.push({
            label: 'Metrics',
            key: 'metrics',
            content: <MetricsTab sourceId={cleanedSourceId} schemaId={schema.id} />,
        })
    }

    if (showDataQuality && schema.table) {
        tabs.push({
            label: 'Data quality',
            key: 'data-quality',
            content: (
                <DataQualityChecksPanel
                    subjectType="table"
                    subjectId={schema.table.id}
                    columns={schema.table.columns ?? []}
                />
            ),
        })
    }

    tabs.push({
        label: 'History',
        key: 'history',
        content: <ActivityLog id={schema.id} scope={ActivityScope.EXTERNAL_DATA_SCHEMA} />,
    })

    const activeTab =
        (!showMetrics && currentTab === 'metrics') ||
        (!showSyncs && currentTab === 'syncs') ||
        (!showDataQuality && currentTab === 'data-quality')
            ? 'configuration'
            : currentTab

    return (
        <SceneContent>
            <SceneTitleSection
                name={schema.label ?? schema.name}
                description={schema.description || undefined}
                resourceType={{ type: 'data_pipeline' }}
            />
            <LemonTabs activeKey={activeTab} tabs={tabs} onChange={setCurrentTab} sceneInset />
        </SceneContent>
    )
}

function ConfigurationSectionLayout({
    sections,
    section,
    onSectionChange,
    body,
}: {
    sections: readonly SchemaConfigurationSection[]
    section: SchemaConfigurationSection
    onSectionChange: (section: SchemaConfigurationSection) => void
    body: JSX.Element
}): JSX.Element {
    return (
        <div className="flex items-start gap-6">
            <nav className="sticky top-[var(--scene-title-section-height,50px)] flex flex-col w-56 flex-shrink-0">
                <ul className="flex flex-col gap-y-px">
                    {sections.map((key) => (
                        <li key={key}>
                            <LemonButton
                                fullWidth
                                size="small"
                                active={section === key}
                                status={key === 'danger-zone' ? 'danger' : undefined}
                                onClick={() => onSectionChange(key)}
                                data-attr={`schema-section-${key}`}
                                className={key === 'danger-zone' && section !== key ? 'mt-2' : undefined}
                            >
                                {SECTION_LABELS[key]}
                            </LemonButton>
                        </li>
                    ))}
                </ul>
            </nav>
            <div className="flex-1 min-w-0">{body}</div>
        </div>
    )
}
