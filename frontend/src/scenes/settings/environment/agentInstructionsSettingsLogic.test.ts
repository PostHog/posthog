import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { agentInstructionsSettingsLogic } from './agentInstructionsSettingsLogic'

describe('agentInstructionsSettingsLogic', () => {
    let logic: ReturnType<typeof agentInstructionsSettingsLogic.build>
    let posted: Record<string, unknown[]>

    beforeEach(() => {
        initKeaTests()
        posted = { project: [], personal: [], triple: [] }
        const record =
            (key: string) =>
            async ({ request }: { request: Request }) => {
                const body = await request.json()
                posted[key].push(body)
                return [200, body]
            }
        useMocks({
            get: {
                '/api/projects/:team_id/tasks/config/': () => [
                    200,
                    { ai_run_preferences: null, agent_instructions: 'Use pnpm.' },
                ],
                '/api/projects/:team_id/tasks/@me/config/': () => [
                    200,
                    { ai_run_preferences: null, resolved_ai_run_defaults: null, agent_instructions: 'Be brief.' },
                ],
            },
            post: {
                '/api/projects/:team_id/tasks/config/agent_instructions/': record('project'),
                '/api/projects/:team_id/tasks/@me/config/agent_instructions/': record('personal'),
                '/api/projects/:team_id/tasks/config/': record('triple'),
                '/api/projects/:team_id/tasks/@me/config/': record('triple'),
            },
        })
        logic = agentInstructionsSettingsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // Posting to the model-preferences endpoint instead would reset the stored model for everyone.
    it.each([
        ['project', 'Use pnpm.', 'setProjectDraft', 'submitProjectDraft', 'saveProjectInstructionsSuccess'],
        ['personal', 'Be brief.', 'setPersonalDraft', 'submitPersonalDraft', 'savePersonalInstructionsSuccess'],
    ] as const)(
        'saves %s instructions through their own endpoint',
        async (scope, stored, setDraft, submit, success) => {
            const valueKey = `${scope}Value` as const
            const dirtyKey = `${scope}Dirty` as const
            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({ [valueKey]: stored, [dirtyKey]: false })

            logic.actions[setDraft]('')
            expect(logic.values[dirtyKey]).toBe(true)
            logic.actions[submit]()

            await expectLogic(logic)
                .toDispatchActions([success])
                .toMatchValues({ [valueKey]: '', [dirtyKey]: false })
            expect(posted[scope]).toEqual([{ agent_instructions: '' }])
            expect(posted.triple).toEqual([])
        }
    )
})
