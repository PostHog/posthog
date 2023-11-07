import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { humanFriendlyTabName, pipelineLogic, singularName } from './pipelineLogic'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'
import { PipelineTabs } from '~/types'

export function Pipeline(): JSX.Element {
    const { currentTab } = useValues(pipelineLogic)

    const singular = singularName(currentTab)
    return (
        <div className="pipeline-scene">
            <PageHeader
                title="Pipeline"
                buttons={
                    <LemonButton data-attr={`new-${singular}`} to={urls.pipelineNew(currentTab)} type="primary">
                        New {singular}
                    </LemonButton>
                }
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.pipeline(tab as PipelineTabs))}
                tabs={Object.values(PipelineTabs).map((tab) => ({
                    label: humanFriendlyTabName(tab),
                    key: tab,
                }))}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Pipeline,
    logic: pipelineLogic,
}
