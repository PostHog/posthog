import { actions, kea, path, reducers, selectors } from 'kea'

import type { streamModalLogicType } from './streamModalLogicType'
import { ExternalDataStripeSource } from '~/types'

const TEST_DATA = [
    {
        streamName: 'test',
        streamId: '1',
        selected: true,
    },
    {
        streamName: 'test2',
        streamId: '2',
        selected: false,
    },
    {
        streamName: 'test3',
        streamId: '3',
        selected: false,
    },
    {
        streamName: 'test4',
        streamId: '4',
        selected: false,
    },
    {
        streamName: 'test5',
        streamId: '5',
        selected: false,
    },
    {
        streamName: 'test6',
        streamId: '6',
        selected: false,
    },
    {
        streamName: 'test7',
        streamId: '7',
        selected: false,
    },
    {
        streamName: 'test8',
        streamId: '8',
        selected: false,
    },
    {
        streamName: 'test9',
        streamId: '9',
        selected: false,
    },
    {
        streamName: 'test10',
        streamId: '10',
        selected: false,
    },
    {
        streamName: 'test11',
        streamId: '11',
        selected: false,
    },
    {
        streamName: 'test12',
        streamId: '12',
        selected: false,
    },
    {
        streamName: 'test13',
        streamId: '13',
        selected: false,
    },
    {
        streamName: 'test14',
        streamId: '14',
        selected: false,
    },
    {
        streamName: 'test15',
        streamId: '15',
        selected: false,
    },
    {
        streamName: 'test16',
        streamId: '16',
        selected: false,
    },
    {
        streamName: 'test17',
        streamId: '17',
        selected: false,
    },
    {
        streamName: 'test18',
        streamId: '18',
        selected: false,
    },
    {
        streamName: 'test19',
        streamId: '19',
        selected: false,
    },
    {
        streamName: 'test20',
        streamId: '20',
        selected: false,
    },
    {
        streamName: 'test21',
        streamId: '21',
        selected: false,
    },
    {
        streamName: 'test22',
        streamId: '22',
        selected: false,
    },
    {
        streamName: 'test23',
        streamId: '23',
        selected: false,
    },
    {
        streamName: 'test24',
        streamId: '24',
        selected: false,
    },
]

export const streamModalLogic = kea<streamModalLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'streamModalLogic']),
    actions({
        toggleStreamModal: (visible: boolean, selectedSource?: ExternalDataStripeSource) => ({
            visible,
            selectedSource: selectedSource || null,
        }),
        toggleStream: (streamId: string) => ({ streamId }),
    }),
    reducers({
        isStreamModalVisible: [
            false,
            {
                toggleStreamModal: (_, { visible }) => visible,
            },
        ],
        selectedStream: [
            null as ExternalDataStripeSource | null,
            {
                toggleStreamModal: (_, { selectedSource }) => selectedSource,
            },
        ],
    }),
    selectors({
        streamOptions: [() => [], () => TEST_DATA],
    }),
])
