import { useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { PipelineNodeLogs } from 'scenes/pipeline/PipelineNodeLogs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityScope, PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

import { PipelineNodeConfiguration } from './PipelineNodeConfiguration'
import { pipelineNodeLogic, PipelineNodeLogicProps } from './pipelineNodeLogic'
import { PipelineNodeMetrics } from './PipelineNodeMetrics'

export const PIPELINE_TAB_TO_NODE_STAGE: Partial<Record<PipelineTab, PipelineStage>> = {
    [PipelineTab.Transformations]: PipelineStage.Transformation,
    [PipelineTab.Destinations]: PipelineStage.Destination,
}

const paramsToProps = ({
    params: { stage, id },
}: {
    params: { stage?: string; id?: string }
}): PipelineNodeLogicProps => {
    const numericId = id && /^\d+$/.test(id) ? parseInt(id) : undefined
    if (!stage || !id) {
        throw new Error('Loaded PipelineNode without either `stage` or `id` passed in')
    }

    return {
        stage: PIPELINE_TAB_TO_NODE_STAGE[stage] || null,
        id: numericId && !isNaN(numericId) ? numericId : id,
    }
}

export const scene: SceneExport = {
    component: PipelineNode,
    logic: pipelineNodeLogic,
    paramsToProps,
}

export function PipelineNode(params: { stage?: string; id?: string } = {}): JSX.Element {
    const { stage, id } = paramsToProps({ params })

    const { currentTab, node, nodeLoading } = useValues(pipelineNodeLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.PIPELINE_UI]) {
        return <p>Pipeline 3000 not available yet</p>
    }

    if (!stage) {
        return <NotFound object="pipeline app stage" />
    }

    if (!nodeLoading && !node) {
        return <NotFound object={stage} />
    }

    const tabToContent: Record<PipelineNodeTab, JSX.Element> = {
        [PipelineNodeTab.Configuration]: <PipelineNodeConfiguration />,
        [PipelineNodeTab.Metrics]: <PipelineNodeMetrics pluginConfigId={id as number} />,
        [PipelineNodeTab.Logs]: <PipelineNodeLogs id={id} stage={stage} />,
        [PipelineNodeTab.History]: <ActivityLog id={id} scope={ActivityScope.PLUGIN} />,
    }

    return (
        <div className="pipeline-app-scene">
            <PageHeader />
            <LemonTabs
                activeKey={currentTab}
                tabs={Object.values(PipelineNodeTab).map(
                    (tab) =>
                        ({
                            label: capitalizeFirstLetter(tab),
                            key: tab,
                            content: tabToContent[tab],
                            link: params.stage ? urls.pipelineNode(stage, id, tab as PipelineNodeTab) : undefined,
                        } as LemonTab<PipelineNodeTab>)
                )}
            />
        </div>
    )
}
