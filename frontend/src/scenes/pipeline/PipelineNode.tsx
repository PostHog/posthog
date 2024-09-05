import { useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { Schemas } from 'scenes/data-warehouse/settings/source/Schemas'
import { Syncs } from 'scenes/data-warehouse/settings/source/Syncs'
import { PipelineNodeLogs } from 'scenes/pipeline/PipelineNodeLogs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityScope, PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

import { BatchExportRuns } from './BatchExportRuns'
import { AppMetricsV2 } from './metrics/AppMetricsV2'
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

    const tabToContent: Partial<Record<PipelineNodeTab, JSX.Element>> =
        node.backend === PipelineBackend.ManagedSource
            ? {
                  [PipelineNodeTab.Schemas]: <Schemas id={node.id} />,
                  [PipelineNodeTab.Syncs]: <Syncs id={node.id} />,
              }
            : {
                  [PipelineNodeTab.Configuration]: <PipelineNodeConfiguration />,
                  [PipelineNodeTab.Metrics]:
                      node.backend === PipelineBackend.HogFunction ? (
                          <AppMetricsV2 id={node.id} />
                      ) : (
                          <PipelineNodeMetrics id={id} />
                      ),
                  [PipelineNodeTab.Logs]: <PipelineNodeLogs id={id} stage={stage} />,
              }

    if (node.backend === PipelineBackend.BatchExport) {
        tabToContent[PipelineNodeTab.Runs] = <BatchExportRuns id={node.id} />
    }

    if (node.backend === PipelineBackend.Plugin) {
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
