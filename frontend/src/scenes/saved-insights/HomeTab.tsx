import posthog from 'posthog-js'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { ActiveUsers } from './ActiveUsers'
import { Activity } from './Activity'
import { FiringAlerts } from './FiringAlerts'
import { NewEvents } from './NewEvents'
import { RecentlyViewed } from './RecentlyViewed'
import { Trending } from './Trending'

export function HomeTab(): JSX.Element {
    useOnMountEffect(() => {
        posthog.capture('product analytics home viewed')
    })

    return (
        <div className="py-4">
            <div className="flex flex-col gap-4 @min-[48rem]/main-content:flex-row @min-[48rem]/main-content:items-start">
                <div className="flex min-w-0 flex-1 flex-col gap-4">
                    <RecentlyViewed />
                    <FiringAlerts />
                    <ActiveUsers />
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-4">
                    <Trending />
                    <NewEvents />
                    <Activity />
                </div>
            </div>
        </div>
    )
}
