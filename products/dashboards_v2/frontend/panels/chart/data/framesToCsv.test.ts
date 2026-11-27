import type { DataFrame } from '../../../query/queryTypes'
import { framesToCsv } from './framesToCsv'

describe('framesToCsv', () => {
    const series = (name: string, times: string[], values: number[]): DataFrame => ({
        name,
        fields: [
            { name: 'time', type: 'time', values: times },
            { name: 'value', type: 'number', values },
        ],
    })

    it.each<{ name: string; frames: DataFrame[]; csv: string[] }>([
        {
            name: 'joins series on their time, and leaves a gap where one has no value',
            frames: [series('Pageviews', ['d1', 'd2'], [1, 2]), series('Sign-ups', ['d2', 'd3'], [5, 6])],
            csv: ['time,Pageviews,Sign-ups', 'd1,1,', 'd2,2,5', 'd3,,6'],
        },
        {
            name: 'names columns by field when a frame holds several values',
            frames: [
                {
                    fields: [
                        { name: 'browser', type: 'string', values: ['Chrome', 'Safari'] },
                        { name: 'visitors', type: 'number', values: [3, 4] },
                        { name: 'sessions', type: 'number', values: [7, 8] },
                    ],
                },
            ],
            csv: ['browser,visitors,sessions', 'Chrome,3,7', 'Safari,4,8'],
        },
        {
            name: 'stacks frames that have no key to join on',
            frames: [
                { name: 'A', fields: [{ name: 'value', type: 'number', values: [1] }] },
                { name: 'B', fields: [{ name: 'value', type: 'number', values: [2] }] },
            ],
            csv: ['series,value', 'A,1', 'B,2'],
        },
        {
            name: 'stacks frames whose key repeats, and stops a cell running as a formula',
            frames: [{ fields: [{ name: 'path', type: 'string', values: ['=1+1', '=1+1'] }] }],
            csv: ['path', `"'=1+1"`, `"'=1+1"`],
        },
    ])('$name', ({ frames, csv }) => {
        expect(framesToCsv(frames).split('\r\n')).toEqual(csv)
    })
})
