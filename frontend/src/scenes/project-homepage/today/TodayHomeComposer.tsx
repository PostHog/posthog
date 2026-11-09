import { useActions } from 'kea'

import { QuillTaskComposerSkeleton } from 'products/posthog_ai/frontend/api/composer'
import { EmbeddedTaskComposer } from 'products/posthog_ai/frontend/api/runner'

import { TODAY_HOME_PANEL_ID, todayHomeComposerLogic } from './todayHomeComposerLogic'

export function TodayHomeComposer(): JSX.Element {
    const { homeTaskStarted } = useActions(todayHomeComposerLogic)

    return (
        <div className="TodayHome__composer" data-attr="today-home-composer">
            <EmbeddedTaskComposer
                panelId={TODAY_HOME_PANEL_ID}
                autoFocus={false}
                onTaskCreated={homeTaskStarted}
                fallback={<QuillTaskComposerSkeleton />}
            />
        </div>
    )
}
