import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { asDisplay } from 'scenes/persons/person-utils'
import { ActivityScoreLabel } from 'scenes/session-recordings/components/RecordingRow'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { ReplayTile } from 'scenes/web-analytics/common'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { SessionRecordingType } from '~/types'

export function WebAnalyticsRecordingsTile({ tile }: { tile: ReplayTile }): JSX.Element {
    const { layout } = tile
    const { replayFilters, webAnalyticsFilters } = useValues(webAnalyticsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const useTileHeaderV2 = featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_TILE_HEADER_V2] === 'test'

    const sessionRecordingsListLogicInstance = sessionRecordingsPlaylistLogic({
        logicKey: 'webAnalytics',
        filters: replayFilters,
    })

    const { sessionRecordings, sessionRecordingsResponseLoading } = useValues(sessionRecordingsListLogicInstance)
    const items = sessionRecordings.slice(0, 5)

    const emptyMessage = !currentTeam?.session_recording_opt_in
        ? {
              title: 'Recordings are not enabled for this project',
              description: 'Once recordings are enabled, new recordings will display here.',
              buttonText: 'Enable recordings',
              buttonTo: urls.settings('project-replay', 'replay'),
          }
        : webAnalyticsFilters.length > 0
          ? {
                title: 'There are no recordings matching the current filters',
                description: 'Try changing the filters, or view all recordings.',
                buttonText: 'View all',
                buttonTo: urls.replay(),
            }
          : {
                title: 'There are no recordings matching this date range',
                description: 'Make sure you have the javascript snippet setup in your website.',
                buttonText: 'Learn more',
                buttonTo: 'https://posthog.com/docs/user-guides/recordings',
            }
    const viewAllButton = (
        <div
            onClick={() => {
                addProductIntentForCrossSell({
                    from: ProductKey.WEB_ANALYTICS,
                    to: ProductKey.SESSION_REPLAY,
                    intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                })
            }}
        >
            <ViewRecordingsPlaylistButton filters={replayFilters} size="small" type="secondary" label="View all" />
        </div>
    )

    const tableContent = sessionRecordingsResponseLoading ? (
        <div className="p-2 deprecated-space-y-6">
            {Array.from({ length: 6 }, (_, index) => (
                <LemonSkeleton key={index} />
            ))}
        </div>
    ) : items.length === 0 && emptyMessage ? (
        <EmptyMessage {...emptyMessage} />
    ) : (
        <LemonTable
            className="mt-4"
            columns={[
                {
                    title: 'Person',
                    render: (_, recording: SessionRecordingType) => (
                        <>
                            <ProfilePicture size="sm" name={asDisplay(recording.person)} className="mr-2" />
                            {asDisplay(recording.person)}{' '}
                        </>
                    ),
                },
                {
                    title: 'Activity',
                    render: (_, recording: SessionRecordingType) => (
                        <>
                            <ActivityScoreLabel score={recording.activity_score} clean={true} />
                        </>
                    ),
                },
                {
                    title: 'Duration',
                    render: (_, recording: SessionRecordingType) => (
                        <>{humanFriendlyDuration(recording.recording_duration)}</>
                    ),
                },
                {
                    title: 'Recording',
                    render: (_, recording: SessionRecordingType) => (
                        <div
                            onClick={() => {
                                addProductIntentForCrossSell({
                                    from: ProductKey.WEB_ANALYTICS,
                                    to: ProductKey.SESSION_REPLAY,
                                    intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                                })
                            }}
                        >
                            <ViewRecordingButton sessionId={recording.id ?? ''} size="xsmall" />
                        </div>
                    ),
                },
            ]}
            dataSource={items}
        />
    )

    return (
        <>
            <div
                className={clsx(
                    'col-span-1 row-span-1 flex flex-col',
                    layout.colSpanClassName ?? 'md:col-span-1',
                    layout.rowSpanClassName ?? 'md:row-span-1',
                    layout.orderWhenLargeClassName ?? '2xl:order-12',
                    layout.className
                )}
            >
                {useTileHeaderV2 ? (
                    <div className="border rounded bg-surface-primary flex-1 flex flex-col py-2 px-1">
                        <div className="flex flex-row items-center self-stretch gap-2 min-h-10 px-3 py-2">
                            <h2 className="flex-1 m-0 text-base font-semibold">Session replay</h2>
                            {viewAllButton}
                        </div>
                        {tableContent}
                    </div>
                ) : (
                    <>
                        <h2 className="m-0 mb-3">Session replay</h2>
                        <div className="border rounded bg-surface-primary flex-1 flex flex-col py-2 px-1">
                            {tableContent}
                        </div>
                        <div className="flex flex-row-reverse my-2">{viewAllButton}</div>
                    </>
                )}
            </div>
        </>
    )
}
