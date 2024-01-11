import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { PluginLogs } from 'scenes/plugins/plugin/PluginLogs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { PipelineAppTabs, PipelineTabs } from '~/types'

import { AppMetrics } from './AppMetrics'
import { pipelineAppLogic } from './pipelineAppLogic'

export const scene: SceneExport = {
    component: PipelineApp,
    logic: pipelineAppLogic,
    paramsToProps: ({ params: { kind, id } }: { params: { kind?: string; id?: string } }) => ({
        kind: kind,
        id: id ? parseInt(id) : 'new',
    }),
}

export function PipelineApp({ kind, id }: { kind?: string; id?: string } = {}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.PIPELINE_UI]) {
        return <p>Pipeline 3000 not available yet</p>
    }
    if (!Object.values(PipelineTabs).includes(kind as PipelineTabs)) {
        return <NotFound object="pipeline app" />
    }
    const { currentTab } = useValues(pipelineAppLogic)

    const confId = id ? parseInt(id) : undefined

    if (!confId) {
        return <Spinner />
    }

    const tab_to_content: Record<PipelineAppTabs, JSX.Element> = {
        [PipelineAppTabs.Configuration]: <div>Configuration editing</div>,
        [PipelineAppTabs.Metrics]: <AppMetrics pluginConfigId={confId} />,
        [PipelineAppTabs.Logs]: <PluginLogs pluginConfigId={confId} />,
    }

    return (
        <div className="pipeline-app-scene">
            <PageHeader />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) =>
                    router.actions.push(urls.pipelineApp(kind as PipelineTabs, confId, tab as PipelineAppTabs))
                }
                tabs={Object.values(PipelineAppTabs).map((tab) => ({
                    label: capitalizeFirstLetter(tab),
                    key: tab,
                    content: tab_to_content[tab],
                }))}
            />
        </div>
    )
}
