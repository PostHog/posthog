import { LemonButton, LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { featureManagementDetailLogic } from './featureManagementDetailLogic'

function Header(): JSX.Element {
    const { activeFeature } = useValues(featureManagementDetailLogic)
    const { deleteFeature } = useActions(featureManagementDetailLogic)

    return (
        <div className="flex justify-between items-center">
            <div className="text-xl font-bold">{activeFeature?.name}</div>
            <More
                overlay={
                    <>
                        <LemonButton fullWidth>Edit</LemonButton>
                        <LemonDivider />
                        <LemonButton status="danger" fullWidth onClick={() => deleteFeature(activeFeature)}>
                            Delete feature
                        </LemonButton>
                    </>
                }
            />
        </div>
    )
}

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
    return (
        <div className="flex flex-col gap-16">
            <Header />
            <Metadata />
            <Rollout />
            <Usage />
            <Activity />
            <History />
            <Permissions />
        </div>
    )
}
