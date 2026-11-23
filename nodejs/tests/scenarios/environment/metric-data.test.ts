import { seriesOf } from './metric-data'

const FROM = Date.parse('2026-11-19T10:00:00Z')
const TO = Date.parse('2026-11-19T10:05:00Z')
const REQUEST = {
    ids: ['max', 'avg'],
    from: FROM,
    to: TO,
    periodMs: 60_000,
    floor: 0,
    subject: (id: string) => `the ${id} series`,
}
const STAMPS = ['2026-11-19T10:01:00+00:00', '2026-11-19T10:02:00+00:00', '2026-11-19T10:03:00+00:00']

const series = (Id: string, fields: Record<string, unknown> = {}): Record<string, unknown> => ({
    Id,
    Label: 'ServerlessDatabaseCapacity',
    Timestamps: STAMPS,
    Values: [1, 1.5, 2],
    StatusCode: 'Complete',
    Messages: [],
    ...fields,
})

const answerOf = (max: Record<string, unknown> = {}, top: Record<string, unknown> = {}): unknown => ({
    MetricDataResults: [series('max', max), series('avg')],
    Messages: [],
    ...top,
})

describe('seriesOf', () => {
    it.each<[string, unknown, RegExp]>([
        ['an answer that is not an object', 'Complete', /shape that is not GetMetricData/],
        ['an answer without MetricDataResults', { Messages: [] }, /shape that is not GetMetricData/],
        ['a series whose Timestamps is not a list', answerOf({ Timestamps: 'now' }), /shape that is not GetMetricData/],
        ['a NextToken', answerOf({}, { NextToken: 'page-2' }), /NextToken, so the answer is only one page/],
        ['a missing series', { MetricDataResults: [series('max')] }, /answered the series max, not max, avg/],
        [
            'a repeated series',
            { MetricDataResults: [series('max'), series('max')] },
            /answered the series max, max, not max, avg/,
        ],
        [
            'an extra series',
            { MetricDataResults: [series('max'), series('avg'), series('min')] },
            /answered the series max, avg, min, not max, avg/,
        ],
        ['no status', answerOf({ StatusCode: undefined }), /^the max series came back with no status, not Complete$/],
        [
            'PartialData',
            answerOf({ StatusCode: 'PartialData', Messages: [{ Code: 'MaxDatapointsExceeded' }] }),
            /^the max series came back PartialData, not Complete: MaxDatapointsExceeded$/,
        ],
        ['Forbidden', answerOf({ StatusCode: 'Forbidden' }), /came back Forbidden, not Complete/],
        ['InternalError', answerOf({ StatusCode: 'InternalError' }), /came back InternalError, not Complete/],
        ['fewer values than timestamps', answerOf({ Values: [1, 1.5] }), /has 3 timestamps and 2 values/],
        ['more values than timestamps', answerOf({ Values: [1, 1.5, 2, 2] }), /has 3 timestamps and 4 values/],
        ['a null value', answerOf({ Values: [1, null, 2] }), /not a finite number at 2026-11-19T10:02:00\+00:00$/],
        ['a NaN value', answerOf({ Values: [1, Number.NaN, 2] }), /not a finite number at /],
        ['an infinite value', answerOf({ Values: [1, Infinity, 2] }), /not a finite number at /],
        ['a string value', answerOf({ Values: [1, '1.5', 2] }), /not a finite number at /],
        [
            'a value below the floor',
            answerOf({ Values: [1, -1, 2] }),
            /has a value below 0 at 2026-11-19T10:02:00\+00:00$/,
        ],
        [
            'a timestamp that is not a time',
            answerOf({ Timestamps: ['unknown', ...STAMPS.slice(1)] }),
            /has a timestamp that is not a time: unknown$/,
        ],
        [
            'a timestamp in epoch seconds',
            answerOf({ Timestamps: [1795600860, ...STAMPS.slice(1)] }),
            /has a timestamp that is not a time: 1795600860$/,
        ],
        [
            'a timestamp without an offset',
            answerOf({ Timestamps: ['2026-11-19T10:01:00', ...STAMPS.slice(1)] }),
            /has a timestamp that is not a time: 2026-11-19T10:01:00$/,
        ],
        [
            'a timestamp finer than a millisecond',
            answerOf({ Timestamps: ['2026-11-19T10:01:00.0001Z', ...STAMPS.slice(1)] }),
            /has a timestamp that is not a time: 2026-11-19T10:01:00.0001Z$/,
        ],
        [
            'a timestamp off the period grid',
            answerOf({ Timestamps: ['2026-11-19T10:01:30+00:00', ...STAMPS.slice(1)] }),
            /has a timestamp off the 60s period of its window: 2026-11-19T10:01:30.000Z$/,
        ],
        [
            'a timestamp before the window',
            answerOf({ Timestamps: ['2026-11-19T09:59:00+00:00', ...STAMPS.slice(1)] }),
            /outside the 2026-11-19T10:00:00.000Z to 2026-11-19T10:05:00.000Z it asked for: 2026-11-19T09:59:00.000Z$/,
        ],
        [
            'a timestamp at the window end',
            answerOf({ Timestamps: [...STAMPS.slice(0, 2), '2026-11-19T10:05:00+00:00'] }),
            /it asked for: 2026-11-19T10:05:00.000Z$/,
        ],
        [
            'descending timestamps',
            answerOf({ Timestamps: [...STAMPS].reverse() }),
            /is not in ascending time order at 2026-11-19T10:02:00.000Z, 2026-11-19T10:01:00.000Z$/,
        ],
        [
            'a repeated timestamp',
            answerOf({ Timestamps: [STAMPS[0], STAMPS[0], STAMPS[2]] }),
            /is not in ascending time order at 2026-11-19T10:01:00.000Z$/,
        ],
    ])('refuses %s', (_shape, answer, reason) => {
        expect(() => seriesOf(answer, REQUEST)).toThrow(reason)
    })

    it.each<[string, unknown, Record<string, { at: number; value: number }[]>]>([
        [
            'the CLI shape, ascending with offsets',
            answerOf(),
            {
                max: [
                    { at: Date.parse(STAMPS[0]), value: 1 },
                    { at: Date.parse(STAMPS[1]), value: 1.5 },
                    { at: Date.parse(STAMPS[2]), value: 2 },
                ],
                avg: [
                    { at: Date.parse(STAMPS[0]), value: 1 },
                    { at: Date.parse(STAMPS[1]), value: 1.5 },
                    { at: Date.parse(STAMPS[2]), value: 2 },
                ],
            },
        ],
        [
            'timestamps with one and two fraction digits',
            {
                MetricDataResults: [
                    { Id: 'max', StatusCode: 'Complete', Timestamps: ['2026-11-19T10:01:00.0Z'], Values: [1] },
                    { Id: 'avg', StatusCode: 'Complete', Timestamps: ['2026-11-19T10:01:00.00+00:00'], Values: [1] },
                ],
            },
            { max: [{ at: Date.parse(STAMPS[0]), value: 1 }], avg: [{ at: Date.parse(STAMPS[0]), value: 1 }] },
        ],
        [
            'a series with no points, its lists left out',
            {
                MetricDataResults: [
                    { Id: 'max', StatusCode: 'Complete' },
                    { Id: 'avg', StatusCode: 'Complete', Timestamps: ['2026-11-19T10:00:00.000Z'], Values: [1] },
                ],
            },
            { max: [], avg: [{ at: FROM, value: 1 }] },
        ],
    ])('reads %s', (_shape, answer, expected) => {
        expect(seriesOf(answer, REQUEST)).toEqual(expected)
    })
})
