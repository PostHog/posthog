import { apiMutator } from 'lib/api-orval-mutator'

import { useMocks } from '~/mocks/jest'

describe('apiMutator', () => {
    it('returns the parsed body of a delete that answers with one', async () => {
        useMocks({ delete: { '/api/projects/:team_id/probe/:id/': { status: 'cancelled', report_id: 7 } } })

        const result = await apiMutator('/api/projects/1/probe/2/', { method: 'DELETE' })

        expect(result).toEqual({ status: 'cancelled', report_id: 7 })
    })

    it('returns null for a delete with no content', async () => {
        useMocks({ delete: { '/api/projects/:team_id/probe/:id/': () => [204] } })

        const result = await apiMutator('/api/projects/1/probe/2/', { method: 'DELETE' })

        expect(result).toBeNull()
    })
})
