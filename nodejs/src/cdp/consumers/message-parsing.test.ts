import { Message } from 'node-rdkafka'

import { assertTeamId, readTeamIdHeader, skipIfMalformed } from './message-parsing'

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
    describe('readTeamIdHeader', () => {
        function withHeaders(headers?: { [key: string]: string | Buffer }[]): Message {
            return { headers } as unknown as Message
        }

        type Headers = { [key: string]: string | Buffer }[]

        it.each<[string, Headers, number]>([
            ['a string value', [{ team_id: '42' }], 42],
            ['a buffer value', [{ team_id: Buffer.from('42') }], 42],
            ['a header beside others', [{ productTrack: 'general' }, { team_id: '42' }], 42],
        ])('reads %s', (_name, headers, expected) => {
            expect(readTeamIdHeader(withHeaders(headers))).toBe(expected)
        })

        // A value that is not a usable team id must not become one. Returning it would make the
        // consumer load another team's destinations for this event, or none at all.
        it.each<[string, Headers | undefined]>([
            ['no headers at all', undefined],
            ['no team_id header', [{ productTrack: 'general' }]],
            ['an empty value', [{ team_id: '' }]],
            ['a value that is not a number', [{ team_id: 'not-a-number' }]],
            ['a value above the int4 range', [{ team_id: '2147483648' }]],
            ['a zero', [{ team_id: '0' }]],
            ['a negative value', [{ team_id: '-1' }]],
            ['a fractional value', [{ team_id: '1.5' }]],
        ])('falls back to the body for %s', (_name, headers) => {
            expect(readTeamIdHeader(withHeaders(headers))).toBeNull()
        })
    })
})
