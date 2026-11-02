import { assertTeamId, skipIfMalformed } from './message-parsing'

describe('message-parsing', () => {
    describe('assertTeamId', () => {
        it.each([1, 2_147_483_647])('accepts team_id %p', (teamId) => {
            expect(assertTeamId({ team_id: teamId })).toEqual({ team_id: teamId })
        })

        it.each([2_147_483_648, 0, -1, 1.5, NaN, '1', null, undefined])('rejects team_id %p', (teamId) => {
            expect(() => assertTeamId({ team_id: teamId })).toThrow('invalid_team_id')
        })
    })

    describe('skipIfMalformed', () => {
        it('reports a thrown non-Error as a reason a person can read', () => {
            // A thrown string carries no `message`. An undefined reason fails the dead-letter produce, so
            // the partition stalls on the very message the record exists to keep.
            const onError = jest.fn()

            const result = skipIfMalformed(
                'Error parsing message',
                () => {
                    throw 'kaboom'
                },
                onError
            )

            expect(result).toBeNull()
            expect(onError).toHaveBeenCalledWith('kaboom')
        })
    })
})
