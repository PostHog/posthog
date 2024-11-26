import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazy, Suspense } from 'react'

const EarlyAccessFeatures = lazy(() =>
    import('scenes/early-access-features/EarlyAccessFeatures').then((module) => ({
        default: module.EarlyAccessFeatures,
    }))
)

export const FEATURE_MANAGEMENT_SCENE_IDS = ['new'] as const
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
        id: 'new',
        title: 'Features',
        component: (
            <Suspense fallback={<LoadingSpinner />}>
                <EarlyAccessFeatures />
            </Suspense>
        ),
    },
]

export const FEATURE_MANAGEMENT_SCENES_MAP: Record<FeatureManagementSceneId, FeatureManagementScene> =
    FEATURE_MANAGEMENT_SCENES.reduce(
        (acc, scene) => ({ ...acc, [scene.id]: scene }),
        {} as Record<FeatureManagementSceneId, FeatureManagementScene>
    )
