import { useActions, useValues } from 'kea'

import { QuillTaskComposerSkeleton } from 'products/posthog_ai/frontend/api/composer'
import { EmbeddedTaskComposer } from 'products/posthog_ai/frontend/api/runner'

import { todayNewsLogic } from './todayNewsLogic'

export function TodayHomeComposer(): JSX.Element {
    const { composerPrefill, composerFocusRequest } = useValues(todayNewsLogic)
    const { homeTaskStarted } = useActions(todayNewsLogic)

    return (
        <div className="TodayHome__composer" data-attr="today-home-composer">
            <EmbeddedTaskComposer
                panelId="today-home"
                autoFocus={false}
                prefillRequest={composerPrefill}
                focusRequest={composerFocusRequest}
                onTaskCreated={homeTaskStarted}
                fallback={<QuillTaskComposerSkeleton />}
            />
        </div>
    )
}
