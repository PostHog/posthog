import { Message } from 'node-rdkafka'

import { Team } from '../../types'
import { HogFunctionInvocationGlobals } from '../types'
import { assertTeamId, parseBatch, skipIfMalformed } from './message-parsing'

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

    describe('parseBatch', () => {
        function message(offset: number): Message {
            return { value: Buffer.from('{}'), offset } as unknown as Message
        }

        function options(
            loadTeam: (teamId: number) => Promise<Team | null>,
            teamIdByOffset: Record<number, number>,
            parkLookupError?: (message: Message, error: string) => boolean,
            dedupeTeamLoads = false
        ) {
            return {
                errorLog: 'Error parsing message',
                parse: (m: Message) => ({
                    teamId: teamIdByOffset[m.offset],
                    toGlobals: (team: Team) =>
                        ({ project: { id: team.id }, event: { uuid: String(m.offset) } }) as HogFunctionInvocationGlobals,
                }),
                loadTeam,
                parkLookupError,
                dedupeTeamLoads,
            }
        }

        it('loads a team once for the whole batch and still builds globals for each of its messages', async () => {
            const loadTeam = jest.fn(async (teamId: number) => ({ id: teamId }) as Team)

            const globals = await parseBatch(
                [message(0), message(1), message(2)],
                options(loadTeam, { 0: 1, 1: 1, 2: 2 }, undefined, true)
            )

            expect(loadTeam.mock.calls.map(([teamId]) => teamId)).toEqual([1, 2])
            expect(globals.map((g) => g.event.uuid)).toEqual(['0', '1', '2'])
        })

        // A loadTeam that counts skipped events has to keep counting one per message, so the
        // default must stay one call per message.
        it('calls loadTeam once per message unless the caller opts in', async () => {
            const loadTeam = jest.fn(async (teamId: number) => ({ id: teamId }) as Team)

            await parseBatch([message(0), message(1), message(2)], options(loadTeam, { 0: 1, 1: 1, 2: 2 }))

            expect(loadTeam.mock.calls.map(([teamId]) => teamId)).toEqual([1, 1, 2])
        })

        it('parks every message of a team whose shared lookup failed, and keeps the rest of the batch', async () => {
            const parkLookupError = jest.fn().mockReturnValue(true)
            const loadTeam = jest.fn(async (teamId: number) => {
                if (teamId === 1) {
                    throw new Error('lookup_failed')
                }
                return { id: teamId } as Team
            })

            const globals = await parseBatch(
                [message(0), message(1), message(2)],
                options(loadTeam, { 0: 1, 1: 1, 2: 2 }, parkLookupError, true)
            )

            expect(parkLookupError).toHaveBeenCalledTimes(2)
            expect(globals.map((g) => g.event.uuid)).toEqual(['2'])
        })
    })
})
