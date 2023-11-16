import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { pipelineAppLogic } from './pipelineAppLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs/LemonTabs'
import { router } from 'kea-router'
import { PipelineAppTabs } from '~/types'
import { urls } from 'scenes/urls'
import { PluginLogs } from 'scenes/plugins/plugin/PluginLogs'
import { Spinner } from '@posthog/lemon-ui'
import { capitalizeFirstLetter } from 'lib/utils'

export const scene: SceneExport = {
    component: PipelineApp,
    logic: pipelineAppLogic,
    paramsToProps: ({ params: { id } }: { params: { id?: string } }) => ({ id: id ? parseInt(id) : 'new' }),
}

export function PipelineApp({ id }: { id?: string } = {}): JSX.Element {
    const { currentTab } = useValues(pipelineAppLogic)

    const confId = id ? parseInt(id) : undefined

    if (!confId) {
        return <Spinner />
    }

    const tab_to_content: Record<PipelineAppTabs, JSX.Element> = {
        [PipelineAppTabs.Configuration]: <div>Configuration editing</div>,
        [PipelineAppTabs.Metrics]: <div>Metrics page</div>,
        [PipelineAppTabs.Logs]: <PluginLogs pluginConfigId={confId} />,
    }

    return (
        <div className="pipeline-app-scene">
            <PageHeader title={`Pipeline App`} />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.pipelineApp(confId, tab as PipelineAppTabs))}
                tabs={Object.values(PipelineAppTabs).map((tab) => ({
                    label: capitalizeFirstLetter(tab),
                    key: tab,
                    content: tab_to_content[tab],
                }))}
            />
        </div>
    )
}
