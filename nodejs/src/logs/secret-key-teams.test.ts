import { PostgresRouter } from '~/common/utils/db/postgres'
import type { Team } from '~/types'

import { SecretKeyTeams } from './secret-key-teams'

describe('SecretKeyTeams', () => {
    const team = { id: 7, api_token: 'phc_example' } as Team
    // `hash_key_value('phs_example')` in posthog/models/utils.py.
    const hash = 'sha256$e39f07893ca51c363342a580d6699460bc91b2f829304ac421b4c02ee99a5fd0'

    it.each([
        ['the team of a key the query returns', [{ secure_value: hash, team_id: 7 }], team],
        ['no team for a key the query does not return', [], null],
    ])('resolves %s', async (_, rows, expected) => {
        const query = jest.fn().mockResolvedValue({ rows })
        const teams = new SecretKeyTeams({ query } as unknown as PostgresRouter, {
            getTeam: (id) => Promise.resolve(id === 7 ? team : null),
        })

        expect(await teams.getTeam('phs_example')).toEqual(expected)
        expect(query.mock.calls[0][2]).toEqual([[hash], 'logs:write'])
    })
})
