import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { PipelineTabs } from '~/types'

import { NewButton } from './NewButton'
import { humanFriendlyTabName, pipelineLogic } from './pipelineLogic'
import { Transformations } from './Transformations'

export function Pipeline(): JSX.Element {
    const { currentTab } = useValues(pipelineLogic)

    return (
        <div className="pipeline-scene">
            <PageHeader
                title="Pipeline"
                caption="Add filters or transformations to the events sent to PostHog or export them to other tools."
                buttons={<NewButton tab={currentTab} />}
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.pipeline(tab as PipelineTabs))}
                tabs={Object.values(PipelineTabs).map((tab) => ({
                    label: humanFriendlyTabName(tab),
                    key: tab,
                }))}
            />

            {!currentTab ? <Spinner /> : currentTab === PipelineTabs.Transformations ? <Transformations /> : null}
        </div>
    )
}

export const scene: SceneExport = {
    component: Pipeline,
    logic: pipelineLogic,
}
