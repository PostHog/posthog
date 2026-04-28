import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { cleanSourceId } from 'products/data_warehouse/frontend/utils'

import { sourceSettingsLogic } from '../SourceScene/tabs/sourceSettingsLogic'
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
    schedule: 'Schedule',
    'danger-zone': 'Danger zone',
}

export function SchemaScene({ sourceId, schemaId }: SchemaSceneProps): JSX.Element {
    if (!sourceId || !schemaId) {
        return <NotFound object="Data warehouse schema" />
    }

    const cleanedSourceId = cleanSourceId(sourceId)
    const settingsLogicProps = { id: cleanedSourceId, availableSources: {} }

    return (
        <BindLogic logic={sourceSettingsLogic} props={settingsLogicProps}>
            <SchemaSceneContent sourceId={sourceId} schemaId={schemaId} />
        </BindLogic>
    )
}

function SchemaSceneContent({ sourceId, schemaId }: SchemaSceneProps): JSX.Element {
    const { currentTab, currentSection, schema, source, sourceLoading } = useValues(
        schemaSceneLogic({ sourceId, schemaId })
    )
    const { setCurrentTab, setCurrentSection } = useActions(schemaSceneLogic({ sourceId, schemaId }))
    const { featureFlags } = useValues(featureFlagLogic)

    const cleanedSourceId = cleanSourceId(sourceId)
    const showMetrics = !!featureFlags[FEATURE_FLAGS.DWH_SOURCE_METRICS]

    useEffect(() => {
        if (!showMetrics && currentTab === 'metrics') {
            setCurrentTab('configuration')
        }
    }, [showMetrics, currentTab, setCurrentTab])

    if (sourceLoading && !source) {
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
                    section={currentSection}
                    onSectionChange={setCurrentSection}
                    body={
                        <ConfigurationTab
                            sourceId={cleanedSourceId}
                            schema={schema}
                            source={source}
                            section={currentSection}
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
    section,
    onSectionChange,
    body,
}: {
    section: SchemaConfigurationSection
    onSectionChange: (section: SchemaConfigurationSection) => void
    body: JSX.Element
}): JSX.Element {
    return (
        <div className="flex items-start gap-6">
            <nav className="sticky top-[var(--scene-title-section-height,50px)] flex flex-col w-56 flex-shrink-0">
                <ul className="flex flex-col gap-y-px">
                    {SCHEMA_CONFIGURATION_SECTIONS.map((key) => (
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
