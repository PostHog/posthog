import { SceneExport } from 'scenes/sceneTypes'
import { ActionsTable } from '../components/ActionsTable'
import { actionsLogic } from '../logics/actionsLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { NewActionButton } from '../components/NewActionButton'
import { SceneContent, SceneDivider, SceneTitleSection } from '~/layout/scenes/SceneContent'

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
                description="Triggered by events and can be used to perform actions such as sending an email, creating a task, or updating a record."
                resourceType={{
                    type: 'action',
                    typePlural: 'actions',
                }}
                docsLink="https://posthog.com/docs/data/actions"
            />
            <SceneDivider />
            <ActionsTable />
        </SceneContent>
    )
}
