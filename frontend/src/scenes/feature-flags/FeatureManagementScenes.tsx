import { Spinner } from '@posthog/lemon-ui'
import { lazy, Suspense } from 'react'

const EarlyAccessFeatures = lazy(() =>
    import('scenes/early-access-features/EarlyAccessFeatures').then((module) => ({
        default: module.EarlyAccessFeatures,
    }))
)
const Experiments = lazy(() =>
    import('scenes/experiments/Experiments').then((module) => ({ default: module.Experiments }))
)
const FeatureFlags = lazy(() => import('./FeatureFlags').then((module) => ({ default: module.FeatureFlags })))

export const FEATURE_MANAGEMENT_SCENE_IDS = ['features', 'flags', 'experiments'] as const
export type FeatureManagementSceneId = (typeof FEATURE_MANAGEMENT_SCENE_IDS)[number]

export type FeatureManagementScene = {
    id: FeatureManagementSceneId
    title: string
    component: JSX.Element
}

const LoadingSpinner = (): JSX.Element => (
    <div className="flex justify-center">
        <Spinner />
    </div>
)

export const FEATURE_MANAGEMENT_SCENES: FeatureManagementScene[] = [
    {
        id: 'features',
        title: 'Features',
        component: (
            <Suspense fallback={<LoadingSpinner />}>
                <EarlyAccessFeatures />
            </Suspense>
        ),
    },
    {
        id: 'flags',
        title: 'Flags',
        component: (
            <Suspense fallback={<LoadingSpinner />}>
                <FeatureFlags />
            </Suspense>
        ),
    },
    {
        id: 'experiments',
        title: 'Experiments',
        component: (
            <Suspense fallback={<LoadingSpinner />}>
                <Experiments />
            </Suspense>
        ),
    },
]

export const FEATURE_MANAGEMENT_SCENES_MAP: Record<FeatureManagementSceneId, FeatureManagementScene> =
    FEATURE_MANAGEMENT_SCENES.reduce(
        (acc, scene) => ({ ...acc, [scene.id]: scene }),
        {} as Record<FeatureManagementSceneId, FeatureManagementScene>
    )
