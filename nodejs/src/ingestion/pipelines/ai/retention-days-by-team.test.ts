import { parseAiEventsRetentionDaysByTeam } from './retention-days-by-team'

describe('parseAiEventsRetentionDaysByTeam', () => {
    it.each([
        ['', []],
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

    it.each(['1:29', '1:366', '1:abc', 'x:90', '1', '1:90,1:120', '1:90.5', '1:90,', '-1:90', '1:90:120'])(
        'rejects %j',
        (raw) => {
            expect(() => parseAiEventsRetentionDaysByTeam(raw)).toThrow('AI_EVENTS_RETENTION_DAYS_BY_TEAM')
        }
    )
})
