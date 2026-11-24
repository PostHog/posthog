import { parseAiEventsRetentionDaysByTeam } from './retention-days-by-team'

describe('parseAiEventsRetentionDaysByTeam', () => {
    it.each([
        ['', []],
        ['1:60', [[1, 60]]],
        ['1:90', [[1, 90]]],
        [
            '1:90, 2:365',
            [
                [1, 90],
                [2, 365],
            ],
        ],
        [
            '1:30,2:365',
            [
                [1, 30],
                [2, 365],
            ],
        ],
    ])('parses %j', (raw, expected) => {
        expect([...parseAiEventsRetentionDaysByTeam(raw)]).toEqual(expected)
    })

    it.each([
        ['1:29,2:90', [[2, 90]]],
        ['1:366,2:90', [[2, 90]]],
        ['1:120,2:90', [[2, 90]]],
        ['1:abc,2:90', [[2, 90]]],
        ['x:90,2:90', [[2, 90]]],
        ['1,2:90', [[2, 90]]],
        ['1:90.5,2:90', [[2, 90]]],
        ['-1:90,2:90', [[2, 90]]],
        ['1:90:120,2:90', [[2, 90]]],
        ['2:90,', [[2, 90]]],
        ['2:90,2:120', [[2, 90]]],
    ])('skips the invalid entry of %j and keeps the rest', (raw, expected) => {
        expect([...parseAiEventsRetentionDaysByTeam(raw)]).toEqual(expected)
    })
})
