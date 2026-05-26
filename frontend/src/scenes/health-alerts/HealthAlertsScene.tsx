import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { HealthAlertsEntryPoint } from './HealthAlertsEntryPoint'

export const scene: SceneExport = {
    component: HealthAlertsScene,
}

export function HealthAlertsScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Health alerts"
                description="Get notified when a PostHog health check fires or recovers. Pick a destination (Slack, Discord, Teams, email, or webhook) and the kinds of checks you care about."
                resourceType={{ type: 'health' }}
            />
            <HealthAlertsEntryPoint />
        </SceneContent>
    )
}

export default HealthAlertsScene
