import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
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

import { cleanSourceId } from 'products/data_warehouse/frontend/utils'

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
    const showMetrics = !!featureFlags[FEATURE_FLAGS.DWH_SOURCE_METRICS]
    const showDescriptions = !!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SEMANTIC_ENRICHMENT]
    const showColumnsSection = supportsColumnSelection
    const visibleSections = SCHEMA_CONFIGURATION_SECTIONS.filter(
        (key) => (key !== 'columns' || showColumnsSection) && (key !== 'descriptions' || showDescriptions)
    )

    useEffect(() => {
        if (!showMetrics && currentTab === 'metrics') {
            setCurrentTab('configuration')
        }
    }, [showMetrics, currentTab, setCurrentTab])

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
                            onViewSyncHistory={() =>
                                router.actions.push(
                                    combineUrl(urls.dataWarehouseSource(sourceId, 'syncs'), {
                                        schema: schema.name,
                                    }).url
                                )
                            }
                        />
                    }
                />
            ),
        },
    ]

    if (showMetrics) {
        tabs.push({
            label: 'Metrics',
            key: 'metrics',
            content: <MetricsTab sourceId={cleanedSourceId} schemaId={schema.id} />,
        })
    }

    tabs.push({
        label: 'History',
        key: 'history',
        content: <ActivityLog id={schema.id} scope={ActivityScope.EXTERNAL_DATA_SCHEMA} />,
    })

    const activeTab = !showMetrics && currentTab === 'metrics' ? 'configuration' : currentTab

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
