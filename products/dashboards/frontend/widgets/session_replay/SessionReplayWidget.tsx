import { useActions } from 'kea'

import { FilmCameraHog } from 'lib/components/hedgehogs'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import 'scenes/session-recordings/playlist/SessionRecordingPreview.scss'
import {
    SessionRecordingPreview,
    SessionRecordingPreviewSkeleton,
} from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

import type { RecordingsQuery } from '~/queries/schema/schema-general'
import type { SessionRecordingType } from '~/types'

import {
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
    WIDGET_LIST_COUNT_RECORDINGS,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import { parseSessionReplayWidgetConfig } from './sessionReplayWidgetConfigValidation'

type SessionReplayWidgetResult = {
    results?: SessionRecordingType[]
    hasMore?: boolean
    limit?: number
    totalCount?: number
    totalCountCapped?: boolean
}

function SessionReplayWidgetRecordingRow({
    recording,
    order,
}: {
    recording: SessionRecordingType
    order: RecordingsQuery['order']
}): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const { reportRecordingOpenedFromRecentRecordingList } = useActions(sessionRecordingEventUsageLogic)

    return (
        <div
            className="border-b"
            onClick={() => {
                openSessionPlayer({ id: recording.id })
                reportRecordingOpenedFromRecentRecordingList()
            }}
        >
            <SessionRecordingPreview recording={recording} order={order} />
        </div>
    )
}

export function SessionReplayWidget({ result, loading, config }: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as SessionReplayWidgetResult | null | undefined
    const recordings = payload?.results ?? []
    const parsedConfig = parseSessionReplayWidgetConfig(config)
    const order = parsedConfig.orderBy as RecordingsQuery['order']
    const hasSavedFilter = !!parsedConfig.savedFilterId

    if (loading) {
        return (
            <WidgetCardContent>
                {Array.from({ length: 4 }, (_, index) => (
                    <div key={index} className="border-b">
                        <SessionRecordingPreviewSkeleton />
                    </div>
                ))}
            </WidgetCardContent>
        )
    }

    if (recordings.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div
                        className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                        data-attr="session-replay-widget-empty-state"
                    >
                        <FilmCameraHog className="size-20 shrink-0" />
                        <p className="m-0 text-base font-semibold text-primary">No recordings yet</p>
                        <p className="m-0 text-sm text-muted">
                            {hasSavedFilter
                                ? 'No session recordings matched this saved filter.'
                                : 'No session recordings matched your filters for this date range.'}
                        </p>
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }

    return (
        <>
            <WidgetCardContent>
                <div className="flex flex-col">
                    {recordings.map((recording) => (
                        <SessionReplayWidgetRecordingRow key={recording.id} recording={recording} order={order} />
                    ))}
                </div>
            </WidgetCardContent>
            <WidgetContentFooter>
                <WidgetListCount
                    shown={recordings.length}
                    totalCount={payload?.totalCount}
                    totalCountIsLowerBound={payload?.totalCountCapped}
                    noun={WIDGET_LIST_COUNT_RECORDINGS}
                    hasMore={payload?.hasMore}
                    dataAttr="session-replay-widget-count"
                />
            </WidgetContentFooter>
        </>
    )
}
