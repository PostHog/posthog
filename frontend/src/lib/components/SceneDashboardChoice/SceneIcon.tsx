import { IconHome, IconPerson } from '@posthog/icons'
import { DashboardCompatibleScenes } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { cn } from 'lib/utils/css-classes'
import { Scene } from 'scenes/sceneTypes'

export function SceneIcon(props: { scene: DashboardCompatibleScenes; size: 'small' | 'large' }): JSX.Element | null {
    const className = cn('text-warning', props.size === 'small' ? 'text-lg' : 'text-3xl')
    if (props.scene === Scene.ProjectHomepage) {
        return <IconHome className={className} />
    } else if (props.scene === Scene.Group) {
        return <IconPerson className={className} />
    } else if (props.scene === Scene.Person) {
        return <IconPerson className={className} />
    }
    return null
}
