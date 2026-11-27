import { PostgresRouter } from '~/common/utils/db/postgres'
import type { Team } from '~/types'

import { SecretKeyTeams, isUnknownToken, loggableToken } from './secret-key-teams'

describe('SecretKeyTeams', () => {
    const team = { id: 7, api_token: 'phc_example' } as Team
    const exampleKeyHash = 'sha256$e39f07893ca51c363342a580d6699460bc91b2f829304ac421b4c02ee99a5fd0'

    const secretKeyTeams = (rows: { secure_value: string; team_id: number; scopes: string[] }[]) => {
        const query = (_use: unknown, _sql: string, [hashes, scope]: [string[], string]) =>
            Promise.resolve({
                rows: rows
                    .filter((row) => hashes.includes(row.secure_value))
                    .map((row) => ({ ...row, can_write_logs: row.scopes.includes(scope) })),
            })
        return new SecretKeyTeams({ query } as unknown as PostgresRouter, {
            getTeam: (id) => Promise.resolve(id === 7 ? team : null),
        })
    }

    it.each([
        ['the team of a key that has the logs:write scope', ['logs:read', 'logs:write'], team, true],
        ['no team for a key without the logs:write scope', ['logs:read'], null, true],
        ['no team for a key with no row', null, null, false],
    ])('resolves %s', async (_, scopes, expectedTeam, expectedExists) => {
        const teams = secretKeyTeams(scopes ? [{ secure_value: exampleKeyHash, team_id: 7, scopes }] : [])

        expect(await teams.getTeam(exampleKeyHash)).toEqual(expectedTeam)
        expect(await teams.exists(exampleKeyHash)).toEqual(expectedExists)
    })

    it.each([
        ['the digest of a key with no row', exampleKeyHash, [], true],
        ['no digest of a key without the logs:write scope', exampleKeyHash, ['logs:read'], false],
        ['no secret key that arrived unhashed', 'phs_unhashed_key', null, false],
        ['a public token', 'phc_example', null, true],
    ])('treats as unknown %s', async (_, token, scopes, expected) => {
        const teams = secretKeyTeams(scopes?.length ? [{ secure_value: exampleKeyHash, team_id: 7, scopes }] : [])

        expect(await isUnknownToken(token, teams)).toEqual(expected)
    })

    it('treats no digest as unknown without a secret key lookup', async () => {
        expect(await isUnknownToken(exampleKeyHash, undefined)).toEqual(false)
    })

    it.each([
        [exampleKeyHash, 'sha256$e39f0789'],
        ['sha256$e39f', 'sha256$'],
        [' phs_unhashed_key', 'phs_'],
        ['phc_example', 'phc_example'],
    ])('logs only the safe part of %s', (token, logged) => {
        expect(loggableToken(token)).toEqual(logged)
    })
})
