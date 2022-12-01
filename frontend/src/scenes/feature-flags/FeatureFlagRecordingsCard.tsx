import { useValues } from 'kea'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { RecordingRow } from 'scenes/project-homepage/RecentRecordings'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { urls } from 'scenes/urls'
import { RecordingFilters, SessionRecordingType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { defaultEntityFilterOnFlag } from './featureFlagLogic'

interface FeatureFlagRecordingsProps {
    flagKey: string
}

export const filtersForFlag = (flagKey: string): Partial<RecordingFilters> => ({
    events: defaultEntityFilterOnFlag(flagKey).events,
})

export function FeatureFlagRecordings({ flagKey }: FeatureFlagRecordingsProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const sessionRecordingsListLogicInstance = sessionRecordingsListLogic({
        key: `feature-flag-${flagKey}`,
        filters: filtersForFlag(flagKey),
    })
    const { sessionRecordings, sessionRecordingsResponseLoading, filters } = useValues(
        sessionRecordingsListLogicInstance
    )

    return (
        <>
            <SessionPlayerModal />
            <CompactList
                title="Recordings with current feature flag"
                viewAllURL={urls.sessionRecordings(undefined, filters)}
                loading={sessionRecordingsResponseLoading}
                emptyMessage={
                    currentTeam?.session_recording_opt_in
                        ? {
                              title: 'There are no recordings for this project',
                              description: 'Make sure you have the javascript snippet setup in your website.',
                              buttonText: 'Learn more',
                              buttonTo: 'https://posthog.com/docs/user-guides/recordings',
                          }
                        : {
                              title: 'Recordings are not enabled for this project',
                              description: 'Once recordings are enabled, new recordings will display here.',
                              buttonText: 'Enable recordings',
                              buttonTo: urls.projectSettings() + '#recordings',
                          }
                }
                items={sessionRecordings.slice(0, 5)}
                renderRow={(recording: SessionRecordingType, index) => (
                    <RecordingRow key={index} recording={recording} />
                )}
            />
        </>
    )
}
