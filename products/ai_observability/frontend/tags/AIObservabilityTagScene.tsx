import { useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'

import { AIObservabilityTag } from './AIObservabilityTag'

export const scene: SceneExport<{ id: string }> = {
    component: AIObservabilityTagScene,
    paramsToProps: ({ params: { id } }) => ({ id }),
    productKey: ProductKey.AI_OBSERVABILITY,
}

export function AIObservabilityTagScene({ id }: { id: string }): JSX.Element {
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)

    if (!receivedFeatureFlags) {
        return (
            <SceneContent>
                <LemonSkeleton className="w-full h-96" />
            </SceneContent>
        )
    }

    if (!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TAGS]) {
        return (
            <SceneContent>
                <LemonBanner type="warning">Taggers are not enabled for this project.</LemonBanner>
            </SceneContent>
        )
    }

    return <AIObservabilityTag id={id} />
}
