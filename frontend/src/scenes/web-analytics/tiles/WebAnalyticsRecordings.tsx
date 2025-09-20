import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { RecordingRow } from 'scenes/session-recordings/components/RecordingRow'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { ReplayTile } from 'scenes/web-analytics/common'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { ProductKey, ReplayTabs } from '~/types'

export function WebAnalyticsRecordingsTile({ tile }: { tile: ReplayTile }): JSX.Element {
    const { layout } = tile
    const { replayFilters, webAnalyticsFilters } = useValues(webAnalyticsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)

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
    const to = items.length > 0 ? urls.replay(ReplayTabs.Home, replayFilters) : urls.replay()
    return (
        <>
            <div
                className={clsx(
                    'col-span-1 row-span-1 flex flex-col',
                    layout.colSpanClassName ?? 'md:col-span-6',
                    layout.rowSpanClassName ?? 'md:row-span-1',
                    layout.orderWhenLargeClassName ?? 'xxl:order-12',
                    layout.className
                )}
            >
                <h2 className="m-0 mb-3">Session replay</h2>
                <div className="border rounded bg-surface-primary flex-1 flex flex-col py-2 px-1">
                    {sessionRecordingsResponseLoading ? (
                        <div className="p-2 deprecated-space-y-6">
                            {Array.from({ length: 6 }, (_, index) => (
                                <LemonSkeleton key={index} />
                            ))}
                        </div>
                    ) : items.length === 0 && emptyMessage ? (
                        <EmptyMessage {...emptyMessage} />
                    ) : (
                        items.map((item, index) => <RecordingRow key={index} recording={item} />)
                    )}
                </div>
                <div className="flex flex-row-reverse my-2">
                    <LemonButton
                        to={to}
                        icon={<IconOpenInNew />}
                        onClick={() => {
                            addProductIntentForCrossSell({
                                from: ProductKey.WEB_ANALYTICS,
                                to: ProductKey.SESSION_REPLAY,
                                intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                            })
                        }}
                        size="small"
                        type="secondary"
                    >
                        View all
                    </LemonButton>
                </div>
            </div>
        </>
    )
}
