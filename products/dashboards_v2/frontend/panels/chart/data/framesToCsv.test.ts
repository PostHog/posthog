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

    it.each<{ name: string; frames: DataFrame[]; csv: string[]; delimiter?: ',' | '\t' }>([
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
        {
            name: 'stops a cell that starts a formula without an equals sign',
            frames: [{ fields: [{ name: 'path', type: 'string', values: ['@SUM(1)', '+1', '-1', '\tx'] }] }],
            csv: ['path', `"'@SUM(1)"`, `"'+1"`, `"'-1"`, `"'\tx"`],
        },
        {
            name: 'writes a list cell as JSON, so it cannot run as a formula',
            frames: [{ fields: [{ name: 'paths', type: 'other', values: [['=1+1'], ['=1+1']] }] }],
            csv: ['paths', '"[""=1+1""]"', '"[""=1+1""]"'],
        },
        {
            name: 'stops a formula with a line break in it',
            frames: [{ fields: [{ name: 'path', type: 'string', values: ['=SUM(1,\n1)'] }] }],
            csv: ['path', `"'=SUM(1,\n1)"`],
        },
        {
            name: 'quotes a tab in pasted text, so it cannot start a cell of its own',
            frames: [{ fields: [{ name: 'path', type: 'string', values: ['safe\t=1+1'] }] }],
            delimiter: '\t',
            csv: ['path', '"safe\t=1+1"'],
        },
        {
            name: 'joins a date and a full timestamp for the same instant into one row',
            frames: [series('Pageviews', ['2026-11-01'], [1]), series('Sign-ups', ['2026-11-01T00:00:00.000Z'], [5])],
            csv: ['time,Pageviews,Sign-ups', '2026-11-01,1,5'],
        },
    ])('$name', ({ frames, csv, delimiter }) => {
        expect(framesToCsv(frames, delimiter).split('\r\n')).toEqual(csv)
    })
})
