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
    }),
    listeners(({ actions }) => ({
        toggleStreamModal: ({ visible, selectedSource }) => {
            if (visible && selectedSource) {
                actions.loadStreamOptions(selectedSource.id)
            }
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
                ]
            },
        ],
    }),
])
