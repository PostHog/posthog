import { useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { PipelineNodeLogs } from 'scenes/pipeline/PipelineNodeLogs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityScope, PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

import { BatchExportRuns } from './BatchExportRuns'
import { PipelineNodeConfiguration } from './PipelineNodeConfiguration'
import { pipelineNodeLogic, PipelineNodeLogicProps } from './pipelineNodeLogic'
import { PipelineNodeMetrics } from './PipelineNodeMetrics'
import { PipelineNodeMetricsV2 } from './PipelineNodeMetricsV2'
import { PipelineBackend } from './types'

export const PIPELINE_TAB_TO_NODE_STAGE: Partial<Record<PipelineTab, PipelineStage>> = {
    [PipelineTab.Transformations]: PipelineStage.Transformation,
    [PipelineTab.Destinations]: PipelineStage.Destination,
    [PipelineTab.SiteApps]: PipelineStage.SiteApp,
    [PipelineTab.ImportApps]: PipelineStage.ImportApp,
    [PipelineTab.DataImport]: PipelineStage.DataImport,
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
    const { currentTab, node } = useValues(pipelineNodeLogic)

    if (!stage) {
        return <NotFound object="pipeline stage" />
    }

    const tabToContent: Partial<Record<PipelineNodeTab, JSX.Element>> = {
        [PipelineNodeTab.Configuration]: <PipelineNodeConfiguration />,
    }

    tabToContent[PipelineNodeTab.Metrics] =
        node.backend === PipelineBackend.HogFunction ? <PipelineNodeMetricsV2 /> : <PipelineNodeMetrics id={id} />
    tabToContent[PipelineNodeTab.Logs] = <PipelineNodeLogs id={id} stage={stage} />

    if (node.backend === PipelineBackend.BatchExport) {
        tabToContent[PipelineNodeTab.Runs] = <BatchExportRuns id={node.id} />
    }

    if ([PipelineBackend.Plugin, PipelineBackend.BatchExport].includes(node.backend)) {
        tabToContent[PipelineNodeTab.History] = <ActivityLog id={id} scope={ActivityScope.PLUGIN} />
    }

    return (
        <>
            <PageHeader />
            <LemonTabs
                activeKey={currentTab}
                tabs={Object.entries(tabToContent).map(
                    ([tab, content]) =>
                        ({
                            label: capitalizeFirstLetter(tab),
                            key: tab,
                            content: content,
                            link: params.stage ? urls.pipelineNode(stage, id, tab as PipelineNodeTab) : undefined,
                        } as LemonTab<PipelineNodeTab>)
                )}
            />
        </>
    )
}
