import { actions, afterMount, connect, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

import { NodeKind, RecordingsQuery } from '~/queries/schema/schema-general'
import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    SessionRecordingType,
    UniversalFilterValue,
} from '~/types'

import type { heatmapRecordingFallbackLogicType } from './heatmapRecordingFallbackLogicType'

export type HeatmapRecordingFallbackLogicProps = {
    url: string
    selectionMode?: 'default' | 'guided'
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

function buildRecordingFiltersForProperty(property: UniversalFilterValue): Partial<RecordingUniversalFilters> {
    return {
        date_from: RECORDING_FALLBACK_LOOKBACK,
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [property],
                },
            ],
        },
    }
}

export function buildRecordingFiltersForUrl(url: string): Partial<RecordingUniversalFilters> {
    return buildRecordingFiltersForProperty({
        type: PropertyFilterType.Recording,
        key: 'visited_page',
        operator: PropertyOperator.IContains,
        value: [url],
    })
}

export function buildRecordingMatchingEventFiltersForUrl(url: string): RecordingUniversalFilters {
    return {
        ...buildRecordingFiltersForProperty({
            type: PropertyFilterType.Event,
            key: '$current_url',
            operator: PropertyOperator.IContains,
            value: [url],
        }),
        duration: [],
    } as RecordingUniversalFilters
}

export const heatmapRecordingFallbackLogic = kea<heatmapRecordingFallbackLogicType>([
    path(['scenes', 'heatmaps', 'components', 'heatmapRecordingFallbackLogic']),
    props({} as HeatmapRecordingFallbackLogicProps),
    key((props) => `${props.selectionMode ?? 'default'}-${props.url}`),
    connect(() => ({
        actions: [sessionPlayerModalLogic, ['openSessionPlayer']],
    })),
    actions({
        loadMatchingRecordings: true,
        openRecording: (recording: Pick<SessionRecordingType, 'id' | 'matching_events'>) => ({ recording }),
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
    listeners(({ actions, props, values }) => ({
        loadMatchingRecordingsSuccess: ({ matchingRecordings }) => {
            posthog.capture('in-app heatmap recording fallback searched', {
                matching_recordings: matchingRecordings?.length ?? 0,
            })
        },
        openRecording: ({ recording }) => {
            posthog.capture('in-app heatmap recording fallback recording opened')
            actions.openSessionPlayer(
                recording,
                null,
                props.selectionMode === 'guided'
                    ? {
                          type: 'heatmap-background-selection',
                          targetUrl: props.url,
                          matchingRecordingCount: values.matchingRecordings?.length ?? 0,
                      }
                    : null
            )
        },
    })),
    afterMount(({ actions }) => {
        actions.loadMatchingRecordings()
    }),
])
