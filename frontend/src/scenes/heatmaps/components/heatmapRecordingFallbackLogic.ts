import { actions, afterMount, connect, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

import { NodeKind, RecordingsQuery } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator, SessionRecordingType } from '~/types'

import type { heatmapRecordingFallbackLogicType } from './heatmapRecordingFallbackLogicType'

export type HeatmapRecordingFallbackLogicProps = {
    url: string
}

const RECORDING_FALLBACK_LOOKBACK = '-30d'

export function buildRecordingsQueryForUrl(url: string): RecordingsQuery {
    return {
        kind: NodeKind.RecordingsQuery,
        order: 'start_time',
        order_direction: 'DESC',
        date_from: RECORDING_FALLBACK_LOOKBACK,
        limit: 3,
        properties: [
            {
                type: PropertyFilterType.Recording,
                key: 'visited_page',
                operator: PropertyOperator.IContains,
                value: [url],
            },
        ],
    }
}

export const heatmapRecordingFallbackLogic = kea<heatmapRecordingFallbackLogicType>([
    path(['scenes', 'heatmaps', 'components', 'heatmapRecordingFallbackLogic']),
    props({} as HeatmapRecordingFallbackLogicProps),
    key((props) => props.url),
    connect(() => ({
        actions: [sessionPlayerModalLogic, ['openSessionPlayer']],
    })),
    actions({
        loadMatchingRecordings: true,
        openRecording: (recordingId: string) => ({ recordingId }),
    }),
    loaders(({ props }) => ({
        matchingRecordings: [
            null as SessionRecordingType[] | null,
            {
                loadMatchingRecordings: async (_, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.recordings.list(buildRecordingsQueryForUrl(props.url))
                    breakpoint()
                    return response.results
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadMatchingRecordingsSuccess: ({ matchingRecordings }) => {
            posthog.capture('in-app heatmap recording fallback searched', {
                matching_recordings: matchingRecordings?.length ?? 0,
            })
        },
        openRecording: ({ recordingId }) => {
            posthog.capture('in-app heatmap recording fallback recording opened')
            actions.openSessionPlayer({ id: recordingId })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadMatchingRecordings()
    }),
])
