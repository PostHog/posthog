import './Today.scss'

import { TodayHomePage } from './TodayHomePage'

/** The Today homepage at `/home`. Its reports open in the Inbox. */
export function TodayHome(): JSX.Element {
    return (
        <div className="Today flex-1 min-h-full @container/today">
            <TodayHomePage />
        </div>
    )
}
