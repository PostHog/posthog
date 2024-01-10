import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { PipelineAppLogs } from 'scenes/plugins/plugin/PipelineAppLogs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { PipelineAppTabs, PipelineTabs } from '~/types'

import { AppMetrics } from './AppMetrics'
import { pipelineAppLogic, PipelineAppLogicProps } from './pipelineAppLogic'

const paramsToProps = ({ params: { kind, id } }: { params: { kind?: string; id?: string } }): PipelineAppLogicProps => {
    const numericId = id && /^\d+$/.test(id) ? parseInt(id) : undefined
    return {
        kind: (kind as PipelineTabs) || PipelineTabs.Destinations,
        id: (numericId && !isNaN(numericId) ? numericId : id) || 'missing',
    }
}

export const scene: SceneExport = {
    component: PipelineApp,
    logic: pipelineAppLogic,
    paramsToProps,
}

export function PipelineApp(params: { kind?: string; id?: string } = {}): JSX.Element {
    const { kind, id } = paramsToProps({ params })
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.PIPELINE_UI]) {
        return <p>Pipeline 3000 not available yet</p>
    }
    if (!Object.values(PipelineTabs).includes(kind)) {
        return <NotFound object="pipeline app" />
    }
    const { currentTab } = useValues(pipelineAppLogic)

    if (!id) {
        return <Spinner />
    }

    const tabToContent: Record<PipelineAppTabs, JSX.Element> = {
        [PipelineAppTabs.Configuration]: <div>Configuration editing</div>,
        [PipelineAppTabs.Metrics]: <AppMetrics pluginConfigId={id as number} />,
        [PipelineAppTabs.Logs]: <PipelineAppLogs id={id} kind={kind} />,
    }

    return (
        <div className="pipeline-app-scene">
            <PageHeader title={`Pipeline App`} />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.pipelineApp(kind, id, tab as PipelineAppTabs))}
                tabs={Object.values(PipelineAppTabs).map((tab) => ({
                    label: capitalizeFirstLetter(tab),
                    key: tab,
                    content: tabToContent[tab],
                }))}
            />
        </div>
    )
}
