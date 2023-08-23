import { Meta } from '@storybook/react'
import { SceneDashboardChoiceRequired } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceRequired'
import { Scene } from 'scenes/sceneTypes'

const meta: Meta<typeof SceneDashboardChoiceRequired> = {
    title: 'Components/Scene Dashboard Choice Required',
    component: SceneDashboardChoiceRequired,
}
export default meta

export function HomePageSceneDashboardChoiceRequired(): JSX.Element {
    return <SceneDashboardChoiceRequired open={() => {}} scene={Scene.ProjectHomepage} />
}

export function PersonPageSceneDashboardChoiceRequired(): JSX.Element {
    return <SceneDashboardChoiceRequired open={() => {}} scene={Scene.Person} />
}

export function GroupPageSceneDashboardChoiceRequired(): JSX.Element {
    return <SceneDashboardChoiceRequired open={() => {}} scene={Scene.Group} />
}
