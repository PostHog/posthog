import './HomeTab.scss'

import { Activity } from './Activity'
import { FiringAlerts } from './FiringAlerts'
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
                <div className="HomeTab__card HomeTab__card--full">
                    <RecentPersons />
                </div>
            </div>
        </div>
    )
}
