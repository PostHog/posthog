import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { ControlOnboarding } from './flows/control/ControlOnboarding'

export const scene: SceneExport = {
    component: Onboarding,
}

// pinned: keys are the variants of the `onboarding-flow-selector` flag. Each flow mounts its own logic.
const ONBOARDING_FLOWS: Record<string, () => JSX.Element> = {
    control: ControlOnboarding,
}

export function Onboarding(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const Flow = ONBOARDING_FLOWS[String(featureFlags[FEATURE_FLAGS.ONBOARDING_FLOW_SELECTOR])] ?? ControlOnboarding
    return <Flow />
}
