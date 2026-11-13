import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { QuillTaskComposerSkeleton } from 'products/posthog_ai/frontend/api/composer'
import { EmbeddedTaskComposer } from 'products/posthog_ai/frontend/api/runner'

import { TodayHomeClassicComposer } from './TodayHomeClassicComposer'
import { TODAY_HOME_PANEL_ID, todayHomeComposerLogic } from './todayHomeComposerLogic'
import { todayLogic } from './todayLogic'
import { TodayStarterSuggestions } from './TodayStarterSuggestions'

export function TodayHomeComposer(): JSX.Element {
    const { isNewProject } = useValues(todayLogic)
    const { prefillRequest } = useValues(todayHomeComposerLogic)
    const { homeTaskStarted } = useActions(todayHomeComposerLogic)
    const postHogAiTasks = useFeatureFlag('PHAI_SANDBOX_MODE')

    return (
        <>
            <div className="TodayHome__composer" data-attr="today-home-composer">
                {postHogAiTasks ? (
                    <EmbeddedTaskComposer
                        panelId={TODAY_HOME_PANEL_ID}
                        autoFocus={false}
                        onTaskCreated={homeTaskStarted}
                        prefillRequest={prefillRequest}
                        fallback={<QuillTaskComposerSkeleton />}
                    />
                ) : (
                    <TodayHomeClassicComposer />
                )}
            </div>
            {/* The starter prompts ask for code changes, which only a task can make. */}
            {postHogAiTasks && isNewProject ? <TodayStarterSuggestions /> : null}
        </>
    )
}
