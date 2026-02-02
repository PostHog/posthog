import './HomeTab.scss'

import { ActiveUsers } from './ActiveUsers'
import { Activity } from './Activity'
import { FiringAlerts } from './FiringAlerts'
import { NewEvents } from './NewEvents'
import { Recents } from './Recents'
import { Trending } from './Trending'

export function HomeTab(): JSX.Element {
    return (
        <div className="HomeTab">
            <div className="HomeTab__columns">
                <div className="HomeTab__column">
                    <div className="HomeTab__card">
                        <Recents />
                    </div>
                    <div className="HomeTab__card">
                        <FiringAlerts />
                    </div>
                    <div className="HomeTab__card">
                        <ActiveUsers />
                    </div>
                </div>
                <div className="HomeTab__column">
                    <div className="HomeTab__card">
                        <Trending />
                    </div>
                    <div className="HomeTab__card">
                        <NewEvents />
                    </div>
                    <div className="HomeTab__card">
                        <Activity />
                    </div>
                </div>
            </div>
        </div>
    )
}
