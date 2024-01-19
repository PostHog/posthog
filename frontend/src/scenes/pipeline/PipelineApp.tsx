import { useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { PipelineAppLogs } from 'scenes/pipeline/PipelineAppLogs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityScope, PipelineAppKind, PipelineAppTab, PipelineTab } from '~/types'

import { PipelineAppConfiguration } from './PipelineAppConfiguration'
import { pipelineAppLogic, PipelineAppLogicProps } from './pipelineAppLogic'
import { PipelineAppMetrics } from './PipelineAppMetrics'

export const PIPELINE_TAB_TO_APP_KIND: Partial<Record<PipelineTab, PipelineAppKind>> = {
    [PipelineTab.Filters]: PipelineAppKind.Filter,
    [PipelineTab.Transformations]: PipelineAppKind.Transformation,
    [PipelineTab.Destinations]: PipelineAppKind.Destination,
}

const paramsToProps = ({
    params: { kindTab, id },
}: {
    params: { kindTab?: string; id?: string }
}): PipelineAppLogicProps => {
    const numericId = id && /^\d+$/.test(id) ? parseInt(id) : undefined
    if (!kindTab || !id) {
        throw new Error('Loaded the PipelineApp without either `kindTab` or `id` passed in')
    }

    return {
        kind: PIPELINE_TAB_TO_APP_KIND[kindTab] || null,
        id: numericId && !isNaN(numericId) ? numericId : id,
    }
}

export const scene: SceneExport = {
    component: PipelineApp,
    logic: pipelineAppLogic,
    paramsToProps,
}

export function PipelineApp(params: { kindTab?: string; id?: string } = {}): JSX.Element {
    const { kind, id } = paramsToProps({ params })

    const { currentTab, loading, maybePlugin } = useValues(pipelineAppLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.PIPELINE_UI]) {
        return <p>Pipeline 3000 not available yet</p>
    }

    if (!kind) {
        return <NotFound object="pipeline app kind" />
    }

    if (!loading && !maybePlugin) {
        return <NotFound object={kind} />
    }

    const tabToContent: Record<PipelineAppTab, JSX.Element> = {
        [PipelineAppTab.Configuration]: <PipelineAppConfiguration />,
        [PipelineAppTab.Metrics]: <PipelineAppMetrics pluginConfigId={id as number} />,
        [PipelineAppTab.Logs]: <PipelineAppLogs id={id} kind={kind} />,
        [PipelineAppTab.History]: <ActivityLog id={id} scope={ActivityScope.PLUGIN} />,
    }

    return (
        <div className="pipeline-app-scene">
            <PageHeader />
            <LemonTabs
                activeKey={currentTab}
                tabs={Object.values(PipelineAppTab).map(
                    (tab) =>
                        ({
                            label: capitalizeFirstLetter(tab),
                            key: tab,
                            content: tabToContent[tab],
                            link: params.kindTab ? urls.pipelineApp(kind, id, tab as PipelineAppTab) : undefined,
                        } as LemonTab<PipelineAppTab>)
                )}
            />
        </div>
    )
}
