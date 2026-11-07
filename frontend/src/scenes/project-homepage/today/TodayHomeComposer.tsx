import { useActions } from 'kea'

import { QuillTaskComposerSkeleton } from 'products/posthog_ai/frontend/api/composer'
import { EmbeddedTaskComposer } from 'products/posthog_ai/frontend/api/runner'

import { todayHomeComposerLogic } from './todayHomeComposerLogic'

export function TodayHomeComposer(): JSX.Element {
    const { homeTaskStarted } = useActions(todayHomeComposerLogic)

    return (
        <div className="TodayHome__composer" data-attr="today-home-composer">
            <EmbeddedTaskComposer
                panelId="today-home"
                autoFocus={false}
                onTaskCreated={homeTaskStarted}
                fallback={<QuillTaskComposerSkeleton />}
            />
        </div>
    )
}
