import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

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
import { SchemaSceneProps, SchemaSceneTab, schemaSceneLogic } from './schemaSceneLogic'

export type { SchemaSceneTab } from './schemaSceneLogic'

export const scene: SceneExport<SchemaSceneProps> = {
    component: SchemaScene,
    logic: schemaSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE,
    paramsToProps: ({ params: { sourceId, schemaId } }) => ({ sourceId, schemaId }),
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
    const { currentTab, schema, source, sourceLoading } = useValues(schemaSceneLogic({ sourceId, schemaId }))
    const { setCurrentTab } = useActions(schemaSceneLogic({ sourceId, schemaId }))
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
            content: <ConfigurationTab sourceId={cleanedSourceId} schema={schema} source={source} />,
        },
    ]

    if (showMetrics) {
        tabs.push({
            label: 'Metrics',
            key: 'metrics',
            content: <MetricsTab sourceId={cleanedSourceId} schemaId={schema.id} />,
        })
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={schema.label ?? schema.name}
                description={schema.description || undefined}
                resourceType={{ type: 'data_pipeline' }}
            />
            <LemonTabs
                activeKey={!showMetrics && currentTab === 'metrics' ? 'configuration' : currentTab}
                tabs={tabs}
                onChange={setCurrentTab}
                sceneInset
            />
        </SceneContent>
    )
}
