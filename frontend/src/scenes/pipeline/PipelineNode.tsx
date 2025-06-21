import { useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { HogFunctionTesting } from 'scenes/hog-functions/testing/HogFunctionTesting'
import { PipelineNodeLogs } from 'scenes/pipeline/PipelineNodeLogs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityScope, PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

import { BatchExportBackfills } from '../data-pipelines/batch-exports/BatchExportBackfills'
import { BatchExportRuns } from '../data-pipelines/batch-exports/BatchExportRuns'
import { HogFunctionLogs } from '../hog-functions/logs/HogFunctionLogs'
import { HogFunctionMetrics } from '../hog-functions/metrics/HogFunctionMetrics'
import { PipelineNodeConfiguration } from './PipelineNodeConfiguration'
import { pipelineNodeLogic, PipelineNodeLogicProps } from './pipelineNodeLogic'
import { PipelineNodeMetrics } from './PipelineNodeMetrics'
import { PipelineBackend } from './types'

export const PIPELINE_TAB_TO_NODE_STAGE: Partial<Record<PipelineTab, PipelineStage>> = {
    [PipelineTab.Transformations]: PipelineStage.Transformation,
    [PipelineTab.Destinations]: PipelineStage.Destination,
    [PipelineTab.SiteApps]: PipelineStage.SiteApp,
    [PipelineTab.ImportApps]: PipelineStage.ImportApp,
    [PipelineTab.Sources]: PipelineStage.Source,
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
        stage: PIPELINE_TAB_TO_NODE_STAGE[stage as PipelineTab] || null,
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
        [PipelineNodeTab.Metrics]:
            node.backend === PipelineBackend.HogFunction ? (
                <HogFunctionMetrics id={node.id} />
            ) : (
                <PipelineNodeMetrics id={id} />
            ),
        [PipelineNodeTab.Logs]:
            node.backend === PipelineBackend.HogFunction ? (
                <HogFunctionLogs hogFunctionId={id.toString().substring(4)} />
            ) : (
                <PipelineNodeLogs id={id} stage={stage} />
            ),
    }

    if (node.backend === PipelineBackend.BatchExport) {
        tabToContent[PipelineNodeTab.Runs] = <BatchExportRuns id={node.id} />
        tabToContent[PipelineNodeTab.Backfills] = <BatchExportBackfills id={node.id} />
    }

    if (node.backend === PipelineBackend.Plugin) {
        tabToContent[PipelineNodeTab.History] = <ActivityLog id={id} scope={ActivityScope.PLUGIN} />
    }

    if (node.backend === PipelineBackend.HogFunction) {
        if (stage === PipelineStage.Destination) {
            tabToContent[PipelineNodeTab.Testing] = <HogFunctionTesting id={node.id} />
        }
        tabToContent[PipelineNodeTab.History] = (
            <ActivityLog
                id={String(id).startsWith('hog-') ? String(id).substring(4) : id}
                scope={ActivityScope.HOG_FUNCTION}
            />
        )
    }

    if (stage === PipelineStage.SiteApp) {
        delete tabToContent[PipelineNodeTab.Logs]
        delete tabToContent[PipelineNodeTab.Metrics]
    }

    return (
        <>
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
