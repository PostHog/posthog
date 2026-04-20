import { ActiveUsers } from './ActiveUsers'
import { Activity } from './Activity'
import { FiringAlerts } from './FiringAlerts'
import { NewEvents } from './NewEvents'
import { RecentlyViewed } from './RecentlyViewed'
import { Trending } from './Trending'

export function HomeTab(): JSX.Element {
    return (
        <div className="py-4">
            <div className="flex flex-col gap-4 md:flex-row md:items-start">
                <div className="flex flex-1 min-w-0 flex-col gap-4">
                    <RecentlyViewed />
                    <FiringAlerts />
                    <ActiveUsers />
                </div>
                <div className="flex flex-1 min-w-0 flex-col gap-4">
                    <Trending />
                    <NewEvents />
                    <Activity />
                </div>
            </div>
        </div>
    )
}
