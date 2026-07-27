import { useValues } from 'kea'
import { router } from 'kea-router'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { HealthAlertsEntryPoint } from './HealthAlertsEntryPoint'

export const scene: SceneExport = {
    component: HealthAlertsScene,
}

function parsePresetKinds(raw: unknown): string[] | undefined {
    if (typeof raw !== 'string' || raw.length === 0) {
        return undefined
    }
    const kinds = raw
        .split(',')
        .map((k) => k.trim())
        .filter(Boolean)
    return kinds.length > 0 ? kinds : undefined
}

export function HealthAlertsScene(): JSX.Element {
    const {
        searchParams: { preset_kinds: rawPresetKinds },
    } = useValues(router)
    const presetKinds = parsePresetKinds(rawPresetKinds)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Health alerts"
                description="Get notified when a PostHog health check fires or recovers. Pick a destination (Slack, Discord, Teams, email, or webhook) and the kinds of checks you care about."
                resourceType={{ type: 'health' }}
            />
            <HealthAlertsEntryPoint presetKinds={presetKinds} />
        </SceneContent>
    )
}

export default HealthAlertsScene
