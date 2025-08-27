import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ActionsTable } from '../components/ActionsTable'
import { NewActionButton } from '../components/NewActionButton'
import { actionsLogic } from '../logics/actionsLogic'

export const scene: SceneExport = {
    component: Actions,
    logic: actionsLogic,
}

export function Actions(): JSX.Element {
    return (
        <SceneContent>
            <PageHeader buttons={<NewActionButton />} />

            <SceneTitleSection
                name="Actions"
                description="Combine several related events into one, which you can then analyze in insights and dashboards as if it were a single event."
                resourceType={{
                    type: 'action',
                    typePlural: 'actions',
                }}
                docsURL="https://posthog.com/docs/data/actions"
            />
            <SceneDivider />
            <ActionsTable />
        </SceneContent>
    )
}
