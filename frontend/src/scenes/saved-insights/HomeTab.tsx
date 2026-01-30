import './HomeTab.scss'

import { Activity } from './Activity'
import { FiringAlerts } from './FiringAlerts'
import { NewEvents } from './NewEvents'
import { RecentPersons } from './RecentPersons'
import { Recents } from './Recents'
import { Trending } from './Trending'

export function HomeTab(): JSX.Element {
    return (
        <div className="HomeTab">
            <div className="HomeTab__grid">
                <div className="HomeTab__card">
                    <Recents />
                </div>
                <div className="HomeTab__card">
                    <Trending />
                </div>
                <div className="HomeTab__card">
                    <FiringAlerts />
                </div>
                <div className="HomeTab__card">
                    <Activity />
                </div>
                <div className="HomeTab__card">
                    <RecentPersons />
                </div>
                <div className="HomeTab__card">
                    <NewEvents />
                </div>
            </div>
        </div>
    )
}
