import { PostgresRouter } from '~/common/utils/db/postgres'
import type { Team } from '~/types'

import { SecretKeyTeams, loggableToken } from './secret-key-teams'

describe('SecretKeyTeams', () => {
    const team = { id: 7, api_token: 'phc_example' } as Team
    const exampleKeyHash = 'sha256$e39f07893ca51c363342a580d6699460bc91b2f829304ac421b4c02ee99a5fd0'

    it.each([
        ['the team of a key that has the logs:write scope', ['logs:read', 'logs:write'], team],
        ['no team for a key without the logs:write scope', ['logs:read'], null],
        ['no team for a key with no row', null, null],
    ])('resolves %s', async (_, scopes, expected) => {
        const rows = scopes ? [{ secure_value: exampleKeyHash, team_id: 7, scopes }] : []
        const query = (_use: unknown, _sql: string, [hashes, scope]: [string[], string]) =>
            Promise.resolve({
                rows: rows.filter((row) => hashes.includes(row.secure_value) && row.scopes.includes(scope)),
            })
        const teams = new SecretKeyTeams({ query } as unknown as PostgresRouter, {
            getTeam: (id) => Promise.resolve(id === 7 ? team : null),
        })

        expect(await teams.getTeam(exampleKeyHash)).toEqual(expected)
    })

    it.each([
        [exampleKeyHash, 'sha256$e39f0789'],
        [' phs_unhashed_key', 'phs_'],
        ['phc_example', 'phc_example'],
    ])('logs only the safe part of %s', (token, logged) => {
        expect(loggableToken(token)).toEqual(logged)
    })
})
