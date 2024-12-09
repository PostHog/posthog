import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { featureManagementDetailLogic } from './featureManagementDetailLogic'

function Metadata(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <h2 className="font-semibold text-lg">Metadata</h2>
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
        </div>
    )
}

function Rollout(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <h2 className="font-semibold text-lg">Rollout</h2>
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
        </div>
    )
}

function Usage(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <h2 className="font-semibold text-lg">Usage</h2>
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
        </div>
    )
}

function Activity(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <h2 className="font-semibold text-lg">Activity</h2>
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
        </div>
    )
}

function History(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <h2 className="font-semibold text-lg">History</h2>
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
        </div>
    )
}

function Permissions(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <h2 className="font-semibold text-lg">Permissions</h2>
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
            <LemonSkeleton className="w-full h-4" active />
        </div>
    )
}

export function FeatureManagementDetail(): JSX.Element {
    const { activeFeature } = useValues(featureManagementDetailLogic)

    return (
        <div className="flex flex-col gap-16">
            <div className="text-xl font-bold">{activeFeature?.name}</div>
            <Metadata />
            <Rollout />
            <Usage />
            <Activity />
            <History />
            <Permissions />
        </div>
    )
}
