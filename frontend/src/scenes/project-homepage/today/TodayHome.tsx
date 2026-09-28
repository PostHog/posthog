import './Today.scss'

import { useMountedLogic, useValues } from 'kea'

import { TodayBriefing } from './TodayBriefing'
import { todayDrawersLogic } from './todayDrawersLogic'
import { TodayEvidenceDrawers } from './TodayEvidenceDrawers'
import { TodayFollowUpPage } from './TodayFollowUpPage'
import { todayLogic } from './todayLogic'
import { TodayNewFlow } from './TodayNewFlow'
import { TodayStoryMissing, TodayStoryPage } from './TodayStoryPage'

/** The Today homepage: the daily briefing, a story, its follow-up, or the New flow, picked from the URL. */
export function TodayHome(): JSX.Element {
    useMountedLogic(todayDrawersLogic)
    const { route, currentStory, storiesReady } = useValues(todayLogic)

    let content: JSX.Element
    if (route.view === 'new') {
        content = <TodayNewFlow />
    } else if (route.view === 'story' || route.view === 'follow-up') {
        if (!storiesReady) {
            content = <div className="TodayStory" />
        } else if (!currentStory) {
            content = <TodayStoryMissing />
        } else if (route.view === 'follow-up') {
            content = <TodayFollowUpPage key={`follow-up-${currentStory.id}`} story={currentStory} />
        } else {
            content = <TodayStoryPage key={currentStory.id} story={currentStory} />
        }
    } else {
        content = <TodayBriefing />
    }

    return (
        <div className="Today flex-1 min-h-full @container/today">
            {content}
            <TodayEvidenceDrawers />
        </div>
    )
}
