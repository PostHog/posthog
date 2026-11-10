import { useActions, useValues } from 'kea'

import { QuillTaskComposerSkeleton } from 'products/posthog_ai/frontend/api/composer'
import { EmbeddedTaskComposer } from 'products/posthog_ai/frontend/api/runner'
import { NewSessionSuggestions } from 'products/tasks/frontend/spaces/NewSessionSuggestions'

import { TODAY_HOME_PANEL_ID, todayHomeComposerLogic } from './todayHomeComposerLogic'
import { todayLogic } from './todayLogic'
import { TODAY_STARTER_SUGGESTIONS } from './todayStarterSuggestions'

export function TodayHomeComposer(): JSX.Element {
    const { isNewProject } = useValues(todayLogic)
    const { prefillRequest } = useValues(todayHomeComposerLogic)
    const { homeTaskStarted, starterSuggestionSelected } = useActions(todayHomeComposerLogic)

    return (
        <div className="TodayHome__composer" data-attr="today-home-composer">
            <EmbeddedTaskComposer
                panelId={TODAY_HOME_PANEL_ID}
                autoFocus={false}
                onTaskCreated={homeTaskStarted}
                prefillRequest={prefillRequest}
                fallback={<QuillTaskComposerSkeleton />}
            />
            {isNewProject ? (
                <div className="pt-4">
                    <NewSessionSuggestions
                        suggestions={TODAY_STARTER_SUGGESTIONS}
                        onSelect={starterSuggestionSelected}
                    />
                </div>
            ) : null}
        </div>
    )
}
