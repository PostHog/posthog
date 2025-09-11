import { dayjs } from 'lib/dayjs'

export const ingestionWarningsResponse = (baseTime: dayjs.Dayjs): { results: Record<string, any> } => {
    return {
        results: [
            {
                type: 'replay_message_too_large',
                lastSeen: baseTime.subtract(1, 'day'),
                sparkline: [[1, baseTime.format('YYYY-MM-DD')]],
                warnings: [
                    {
                        type: 'replay_message_too_large',
                        timestamp: baseTime.subtract(1, 'day'),
                        details: {
                            timestamp: 'not a date',
                            replayRecord: { session_id: 'some uuid' },
                        },
                    },
                ],
                count: 1,
            },
            {
                type: 'replay_timestamp_invalid',
                lastSeen: baseTime.subtract(1, 'day'),
                sparkline: [[1, baseTime.format('YYYY-MM-DD')]],
                warnings: [
                    {
                        type: 'replay_timestamp_invalid',
                        timestamp: baseTime.subtract(1, 'day'),
                        details: {
                            timestamp: 'not a date',
                            replayRecord: { session_id: 'some uuid' },
                        },
                    },
                ],
                count: 1,
            },
            {
                type: 'replay_timestamp_too_far',
                lastSeen: baseTime.subtract(1, 'day'),
                sparkline: [[1, baseTime.subtract(1, 'day').format('YYYY-MM-DD')]],
                warnings: [
                    {
                        type: 'replay_timestamp_too_far',
                        timestamp: baseTime.subtract(1, 'day'),
                        details: {
                            timestamp: baseTime.add(4, 'day').toISOString(),
                            replayRecord: { session_id: 'some uuid' },
                            daysFromNow: 4,
                        },
                    },
                ],
                count: 1,
            },
            {
                type: 'event_timestamp_in_future',
                lastSeen: baseTime.subtract(1, 'day').toISOString(),
                sparkline: [
                    // don't have to be in order
                    [1, baseTime.subtract(1, 'day').format('YYYY-MM-DD')],
                    [2, baseTime.subtract(4, 'day').format('YYYY-MM-DD')],
                    [1, baseTime.subtract(9, 'day').format('YYYY-MM-DD')],
                    [1, baseTime.format('YYYY-MM-DD')],
                    [1, baseTime.subtract(5, 'day').format('YYYY-MM-DD')],
                    [3, baseTime.subtract(12, 'day').format('YYYY-MM-DD')],
                ],
                warnings: [
                    {
                        type: 'event_timestamp_in_future',
                        timestamp: baseTime.subtract(1, 'day'),
                        details: {
                            timestamp: '2023-06-07T15:10:49.765Z',
                            sentAt: '1970-01-01T00:00:02.040936+00:00',
                            offset: '',
                            now: '2023-06-07T15:10:50.103781+00:00',
                            result: '2076-11-11T06:21:37.828Z',
                            eventUuid: '01889669-179e-7ab7-8535-821a78c8388e',
                            eventName: '$capture_metrics',
                        },
                    },
                    {
                        type: 'event_timestamp_in_future',
                        timestamp: baseTime.subtract(1, 'day'),
                        details: {
                            timestamp: '2023-06-12T17:48:30.647Z',
                            sentAt: '2023-06-05T11:56:20.575000+00:00',
                            offset: '',
                            now: '2023-06-05T11:56:20.973420+00:00',
                            result: '2023-06-12T17:48:31.045Z',
                            eventUuid: '01888b6a-5274-0002-6b7e-41a5b2d94a43',
                            eventName: 'client_request_failure',
                        },
                    },
                    {
                        type: 'event_timestamp_in_future',
                        timestamp: baseTime.subtract(3, 'day'),
                        details: {
                            timestamp: '2023-06-12T17:43:24.839Z',
                            sentAt: '2023-06-05T11:56:20.575000+00:00',
                            offset: '',
                            now: '2023-06-05T11:56:20.973420+00:00',
                            result: '2023-06-12T17:43:25.237Z',
                            eventUuid: '01888b6a-5274-0001-7c18-3db548460528',
                            eventName: 'client_request_failure',
                        },
                    },
                    {
                        type: 'event_timestamp_in_future',
                        timestamp: baseTime.subtract(3, 'day'),
                        details: {
                            timestamp: '2023-05-25T12:16:20.389Z',
                            sentAt: '1970-01-01T00:00:01.312112+00:00',
                            offset: '',
                            now: '2023-05-25T12:16:21.836131+00:00',
                            result: '2076-10-16T00:32:40.913Z',
                            eventUuid: '018852d6-b14c-0000-9d40-4f6caebf93c0',
                            eventName: '$capture_metrics',
                        },
                    },
                    {
                        type: 'event_timestamp_in_future',
                        timestamp: baseTime.subtract(3, 'day'),
                        details: {
                            timestamp: '2023-05-20T12:41:05.910Z',
                            sentAt: '1970-01-01T00:00:01.260819+00:00',
                            offset: '',
                            now: '2023-05-20T12:41:06.159219+00:00',
                            result: '2076-10-06T01:22:10.809Z',
                            eventUuid: '0188392d-8b6f-0000-e73c-ee83f1413a5a',
                            eventName: '$capture_metrics',
                        },
                    },
                    {
                        type: 'event_timestamp_in_future',
                        timestamp: baseTime.subtract(12, 'day'),
                        details: {
                            timestamp: '2023-05-18T22:15:54.943Z',
                            sentAt: '1970-01-01T00:00:03.337903+00:00',
                            offset: '',
                            now: '2023-05-18T22:15:55.248965+00:00',
                            result: '2076-10-02T20:31:46.854Z',
                            eventUuid: '018830ef-1671-0000-341c-bf64a7c23915',
                            eventName: '$capture_metrics',
                        },
                    },
                    {
                        type: 'event_timestamp_in_future',
                        timestamp: baseTime.subtract(12, 'day'),
                        details: {
                            timestamp: '2023-05-17T13:17:20.687Z',
                            sentAt: '1970-01-01T00:00:02.401985+00:00',
                            offset: '',
                            now: '2023-05-17T13:17:20.888451+00:00',
                            result: '2076-09-30T02:34:39.174Z',
                            eventUuid: '018829db-a678-0000-a45e-85884574b83e',
                            eventName: '$capture_metrics',
                        },
                    },
                    {
                        type: 'event_timestamp_in_future',
                        timestamp: baseTime.subtract(12, 'day'),
                        details: {
                            timestamp: '2023-05-17T04:33:53.725Z',
                            sentAt: '1970-01-01T00:00:00.849001+00:00',
                            offset: '',
                            now: '2023-05-17T04:34:04.697751+00:00',
                            result: '2076-09-29T09:07:57.573Z',
                            eventUuid: '018827fc-951a-0000-2f64-7ae5477af4cd',
                            eventName: '$pageview',
                        },
                    },
                    {
                        type: 'event_timestamp_in_future',
                        timestamp: baseTime.subtract(12, 'day'),
                        details: {
                            timestamp: '2023-05-17T04:34:03.195Z',
                            sentAt: '1970-01-01T00:00:01.532197+00:00',
                            offset: '',
                            now: '2023-05-17T04:34:04.661606+00:00',
                            result: '2076-09-29T09:08:06.324Z',
                            eventUuid: '018827fc-94f6-0000-0dde-8a8dc2ca4594',
                            eventName: '$pageleave',
                        },
                    },
                ],
                count: 9,
            },
        ],
    }
}
