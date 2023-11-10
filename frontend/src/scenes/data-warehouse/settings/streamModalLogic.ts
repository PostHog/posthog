import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import type { streamModalLogicType } from './streamModalLogicType'
import { ExternalDataSource, ExternalDataSourceStreamOptions } from '~/types'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

export const streamModalLogic = kea<streamModalLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'streamModalLogic']),
    actions({
        toggleStreamModal: (visible: boolean, selectedSource?: ExternalDataSource) => ({
            visible,
            selectedSource: selectedSource || null,
        }),
        toggleStream: (streamId: string) => ({ streamId }),
        loadStreamOptions: (sourceId: string) => ({ sourceId }),
        updateStreamOption: (streamName: string, selected: boolean) => ({ streamName, selected }),
    }),
    loaders(({ values }) => ({
        streamOptions: [
            {
                available_streams_for_connection: [],
                current_connection_streams: [],
            } as ExternalDataSourceStreamOptions,
            {
                loadStreamOptions: async ({ sourceId }) => {
                    if (values.selectedStream) {
                        return await api.externalDataSources.streams.list(sourceId)
                    } else {
                        return {
                            available_streams_for_connection: [],
                            current_connection_streams: [],
                        }
                    }
                },
            },
        ],
    })),
    reducers({
        isStreamModalVisible: [
            false,
            {
                toggleStreamModal: (_, { visible }) => visible,
            },
        ],
        selectedStream: [
            null as ExternalDataSource | null,
            {
                toggleStreamModal: (_, { selectedSource }) => selectedSource,
            },
        ],
        streamOptions: [
            {
                available_streams_for_connection: [],
                current_connection_streams: [],
            } as ExternalDataSourceStreamOptions,
            {
                updateStreamOption: (state, { streamName, selected }) => {
                    if (selected) {
                        return {
                            ...state,
                            available_streams_for_connection: state.available_streams_for_connection.filter(
                                (stream) => stream.streamName !== streamName
                            ),
                            current_connection_streams: [...state.current_connection_streams, { streamName }],
                        }
                    } else {
                        return {
                            ...state,
                            available_streams_for_connection: [
                                ...state.available_streams_for_connection,
                                { streamName },
                            ],
                            current_connection_streams: state.current_connection_streams.filter(
                                (stream) => stream.streamName !== streamName
                            ),
                        }
                    }
                },
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        toggleStreamModal: ({ visible, selectedSource }) => {
            if (visible && selectedSource) {
                actions.loadStreamOptions(selectedSource.id)
            }
        },
        updateStreamOption: async () => {
            const streamNames = values.streamOptions.current_connection_streams.map((stream) => stream.streamName)
            values.selectedStream &&
                (await api.externalDataSources.streams.update(values.selectedStream.id, streamNames))
        },
    })),
    selectors({
        formattedStreamOptions: [
            (s) => [s.streamOptions],
            (streamOptions) => {
                return [
                    ...streamOptions.current_connection_streams.map((stream) => ({
                        streamName: stream.streamName,
                        selected: true,
                    })),
                    ...streamOptions.available_streams_for_connection.map((stream) => ({
                        streamName: stream.streamName,
                        selected: false,
                    })),
                ].sort((a, b) => a.streamName.localeCompare(b.streamName))
            },
        ],
    }),
])
