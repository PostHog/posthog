import { LemonSwitch } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { RecordingUniversalFilters } from '~/types'

export function RecordingEventMatchScopeSwitch({
    filters,
    setFilters,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element | null {
    const enabled = useFeatureFlag('REPLAY_EVENT_MATCH_SCOPE')
    if (!enabled) {
        return null
    }

    return (
        <LemonSwitch
            bordered
            size="small"
            checked={filters.event_match_scope === 'recording'}
            onChange={(checked) => setFilters({ event_match_scope: checked ? 'recording' : undefined })}
            label="Only match events inside the recording"
            tooltip="By default, event and property filters match anywhere in the session, including moments before the recording starts or after it ends. Turn this on to match only events inside the recording, so the matched moment is in the video."
            data-attr="session-recordings-event-match-scope"
        />
    )
}
