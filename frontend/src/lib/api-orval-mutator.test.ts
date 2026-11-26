import { apiMutator } from 'lib/api-orval-mutator'

import { useMocks } from '~/mocks/jest'

describe('apiMutator', () => {
    it.each([{ 'X-PostHog-Environment-Id': '2' }, new Headers({ 'X-PostHog-Environment-Id': '2' })])(
        'preserves environment headers and parses a delete response with %p',
        async (headers) => {
            useMocks({
                delete: {
                    '/api/projects/:team_id/probe/:id/': ({ request }) => ({
                        status: 'cancelled',
                        report_id: 7,
                        environment_id: request.headers.get('X-PostHog-Environment-Id'),
                    }),
                },
            })

            const result = await apiMutator('/api/projects/1/probe/2/', { method: 'DELETE', headers })

            expect(result).toEqual({ status: 'cancelled', report_id: 7, environment_id: '2' })
        }
    )

    it('returns null for a delete with no content', async () => {
        useMocks({ delete: { '/api/projects/:team_id/probe/:id/': () => [204] } })

        const result = await apiMutator('/api/projects/1/probe/2/', { method: 'DELETE' })

        expect(result).toBeNull()
    })
})
