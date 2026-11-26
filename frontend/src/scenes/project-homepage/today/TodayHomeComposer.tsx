import { useActions, useValues } from 'kea'

import { QuillTaskComposerSkeleton } from 'products/posthog_ai/frontend/api/composer'
import { EmbeddedTaskComposer } from 'products/posthog_ai/frontend/api/runner'

import { TODAY_HOME_PANEL_ID, todayHomeComposerLogic } from './todayHomeComposerLogic'
import { todayLogic } from './todayLogic'
import { TodayStarterSuggestions } from './TodayStarterSuggestions'

export function TodayHomeComposer(): JSX.Element {
    const { isNewProject } = useValues(todayLogic)
    const { prefillRequest } = useValues(todayHomeComposerLogic)
    const { homeTaskStarted } = useActions(todayHomeComposerLogic)

    return (
        <>
            <div className="TodayHome__composer" data-attr="today-home-composer">
                <EmbeddedTaskComposer
                    panelId={TODAY_HOME_PANEL_ID}
                    autoFocus={false}
                    onTaskCreated={homeTaskStarted}
                    prefillRequest={prefillRequest}
                    fallback={<QuillTaskComposerSkeleton />}
                />
            </div>
            {isNewProject ? <TodayStarterSuggestions /> : null}
        </>
    )
}
