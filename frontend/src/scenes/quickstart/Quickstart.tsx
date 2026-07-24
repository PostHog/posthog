import { useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { QuickstartFullPage } from './full-page/QuickstartFullPage'
import { quickstartLogic } from './quickstartLogic'
import { isQuickstartHomepageEnabled } from './quickstartVariant'
import { QuickstartSimplified } from './simplified/QuickstartSimplified'

export const scene: SceneExport = {
    component: Quickstart,
    logic: quickstartLogic,
}

export function Quickstart(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const quickstartVariant = featureFlags[FEATURE_FLAGS.QUICKSTART_HOMEPAGE]

    if (!isQuickstartHomepageEnabled(quickstartVariant)) {
        // Flags are still loading, or quickstartLogic is redirecting home
        return <SpinnerOverlay sceneLevel />
    }
    return quickstartVariant === 'test2' ? <QuickstartSimplified /> : <QuickstartFullPage />
}

export default Quickstart
