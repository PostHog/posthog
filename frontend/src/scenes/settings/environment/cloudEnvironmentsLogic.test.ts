import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { cloudEnvironmentsLogic } from './cloudEnvironmentsLogic'

const ENVIRONMENT = {
    id: '0190e5a3-0000-7000-8000-000000000001',
    name: 'Web app',
    network_access_level: 'custom',
    allowed_domains: ['api.example.com'],
    include_default_domains: true,
    repositories: ['example/web'],
    has_environment_variables: true,
    environment_variable_keys: ['API_TOKEN'],
    private: false,
    internal: false,
    custom_image_id: '0190e5a3-0000-7000-8000-0000000000c1',
}

describe('cloudEnvironmentsLogic', () => {
    let logic: ReturnType<typeof cloudEnvironmentsLogic.build>
    let patchBody: Record<string, unknown> | null

    beforeEach(() => {
        patchBody = null
        useMocks({
            get: { '/api/projects/:team/sandbox_environments/': { count: 1, results: [ENVIRONMENT] } },
            patch: {
                '/api/projects/:team/sandbox_environments/:id/': async ({ request }) => {
                    patchBody = (await request.json()) as Record<string, unknown>
                    return [200, { ...ENVIRONMENT, ...patchBody }]
                },
            },
        })
        initKeaTests()
        logic = cloudEnvironmentsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('saves an edit without touching the stored environment variables', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.editEnvironment(logic.values.environments![0])
        logic.actions.updateDraft({ name: 'Web app v2' })
        await expectLogic(logic, () => logic.actions.saveDraft()).toFinishAllListeners()

        expect(patchBody).toMatchObject({
            name: 'Web app v2',
            allowed_domains: ['api.example.com'],
            private: false,
            custom_image_id: '0190e5a3-0000-7000-8000-0000000000c1',
        })
        expect(patchBody).not.toHaveProperty('environment_variables')
        expect(logic.values.draft).toBeNull()
    })

    it.each([
        ['an empty name', { name: '  ' }, 'Enter a name'],
        [
            'custom access with no domains',
            { network_access_level: 'custom', allowed_domains: [], include_default_domains: false },
            'Add at least one allowed domain',
        ],
    ])('blocks saving with %s', async (_name, changes, expected) => {
        logic.actions.startNewEnvironment()
        logic.actions.updateDraft({ name: 'Web app', ...changes } as any)

        expect(logic.values.draftError).toBe(expected)
    })
})
