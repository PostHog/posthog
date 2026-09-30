import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

export function useAgentTaskUrl(): (taskId: string) => string {
    const showDesktopEntryPoints = useFeatureFlag('POSTHOG_DESKTOP_ENTRY_POINTS')
    return showDesktopEntryPoints ? urls.codeTaskLink : urls.taskDetail
}
