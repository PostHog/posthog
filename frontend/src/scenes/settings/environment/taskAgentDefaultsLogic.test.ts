import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { taskAgentDefaultsLogic } from './taskAgentDefaultsLogic'

describe('taskAgentDefaultsLogic', () => {
    let logic: ReturnType<typeof taskAgentDefaultsLogic.build>
    let posted: any[]

    function useConfigMocks(myPreferences: Record<string, any> | null): void {
        posted = []
        useMocks({
            get: {
                '/api/projects/:team_id/tasks/config/': () => [200, { ai_run_preferences: null }],
                '/api/projects/:team_id/tasks/@me/config/': () => [
                    200,
                    { ai_run_preferences: myPreferences, resolved_ai_run_defaults: null },
                ],
                '/api/projects/:team_id/tasks/models/': () => [200, { models: [] }],
            },
            post: {
                '/api/projects/:team_id/tasks/@me/config/': async ({ request }) => {
                    posted.push(await request.json())
                    return [200, { ai_run_preferences: null, resolved_ai_run_defaults: null }]
                },
            },
        })
    }

    function mount(): void {
        logic = taskAgentDefaultsLogic()
        logic.mount()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // Resetting is the only way back to inheriting once a personal default is stored, so it has to clear
    // the stored preference server-side rather than just blank the pickers.
    it('clears the stored preference and drops back to the project default', async () => {
        useConfigMocks({ runtime_adapter: 'claude', model: 'claude-opus-5', reasoning_effort: 'high' })
        mount()
        await expectLogic(logic).toDispatchActions(['loadMyConfigSuccess']).toMatchValues({
            canResetMyPreference: true,
        })

        logic.actions.resetMyPreference()

        await expectLogic(logic)
            .toDispatchActions(['saveMyPreferencesSuccess'])
            .toMatchValues({
                myDraft: { model: null, reasoning_effort: null },
                canResetMyPreference: false,
                myDraftDirty: false,
            })
        expect(posted).toEqual([{ runtime_adapter: null, model: null, reasoning_effort: null }])
    })

    // Nothing stored and nothing picked means there's nothing to fall back to — the button has to say so
    // rather than post an empty preference over an already-empty one.
    it('has nothing to reset while the project default is already what applies', async () => {
        useConfigMocks(null)
        mount()

        await expectLogic(logic).toDispatchActions(['loadMyConfigSuccess']).toMatchValues({
            canResetMyPreference: false,
            myDraftDirty: false,
        })

        // An unsaved pick is resettable too: reset discards it as well as anything stored.
        logic.actions.setMyDraft({ model: 'claude-opus-5' })
        await expectLogic(logic).toMatchValues({ canResetMyPreference: true, myDraftDirty: true })
    })
})
