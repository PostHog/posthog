import { useMocks } from '~/mocks/jest'

describe('mocksToHandlers', () => {
    it('answers a projects request with the handler registered on the environments twin', async () => {
        useMocks({ get: { '/api/environments/:team_id/alias_probe/': { hit: 'environments' } } })

        const response = await fetch('/api/projects/1/alias_probe/')

        expect(await response.json()).toEqual({ hit: 'environments' })
    })

    it('does not answer an environments request with a handler registered on the projects path', async () => {
        useMocks({ get: { '/api/projects/:team_id/alias_probe/': { hit: 'projects' } } })

        const response = await fetch('/api/environments/1/alias_probe/')

        // The unhandled-request floor from `jest.ts`, which proves the projects handler was not used.
        expect(await response.json()).toEqual({ results: [], count: 0, next: null, previous: null })
    })

    it.each([
        ['matching trailing slashes', '/api/environments/:team_id/alias_probe/', '/api/projects/:team_id/alias_probe/'],
        [
            'mismatched trailing slashes',
            '/api/environments/:team_id/alias_probe/',
            '/api/projects/:team_id/alias_probe',
        ],
        ['different param names', '/api/environments/:team_id/alias_probe/', '/api/projects/:team/alias_probe/'],
    ])('keeps an explicit projects registration ahead of the twin, %s', async (_name, envPath, projectsPath) => {
        useMocks({ get: { [envPath]: { hit: 'environments' }, [projectsPath]: { hit: 'projects' } } })

        const response = await fetch('/api/projects/1/alias_probe/')

        expect(await response.json()).toEqual({ hit: 'projects' })
    })

    it('keeps a specific projects route ahead of a broader twin registered before it', async () => {
        useMocks({
            get: {
                '/api/environments/:id/alias_probe/:probeId': { hit: 'environments' },
                '/api/projects/:id/alias_probe/summary': { hit: 'projects' },
            },
        })

        const response = await fetch('/api/projects/1/alias_probe/summary')

        expect(await response.json()).toEqual({ hit: 'projects' })
    })
})
