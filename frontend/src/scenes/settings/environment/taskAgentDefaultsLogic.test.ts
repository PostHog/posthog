import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { decodeModelChoice, encodeModelChoice, taskAgentDefaultsLogic } from './taskAgentDefaultsLogic'

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
            },
            post: {
                '/api/projects/:team_id/tasks/@me/config/': async ({ request }) => {
                    posted.push(await request.json())
                    return [200, { ai_run_preferences: null, resolved_ai_run_defaults: null }]
                },
                '/api/projects/:team_id/tasks/config/': async ({ request }) => {
                    const body = await request.json()
                    return [200, { ai_run_preferences: body }]
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
        await expectLogic(logic)
            .toDispatchActions(['loadMyConfigSuccess'])
            .toMatchValues({
                canResetMyPreference: true,
                myDraft: { model: 'claude-opus-5', reasoning_effort: 'high', runtime: 'acp' },
            })

        logic.actions.resetMyPreference()

        await expectLogic(logic)
            .toDispatchActions(['saveMyPreferencesSuccess'])
            .toMatchValues({
                myDraft: { model: null, reasoning_effort: null, runtime: null },
                canResetMyPreference: false,
                myDraftDirty: false,
            })
        expect(posted).toEqual([{ runtime: null, runtime_adapter: null, model: null, reasoning_effort: null }])
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

    // Pi and the ACP adapters serve some of the same model ids — `gpt-5.6-terra` is both Pi's default
    // and a Codex model. Keyed on the model alone the two options collide, and picking the Codex one
    // read as "no change", so a default the person moved off Pi stayed on it.
    it('keeps the Pi and ACP options distinct when they name the same model', () => {
        const shared = 'gpt-5.6-terra'
        const onPi = encodeModelChoice({ model: shared, runtime: 'pi' })
        const onAcp = encodeModelChoice({ model: shared, runtime: 'acp' })

        expect(onPi).not.toEqual(onAcp)
        expect(decodeModelChoice(onPi)).toEqual({ model: shared, runtime: 'pi' })
        expect(decodeModelChoice(onAcp)).toEqual({ model: shared, runtime: 'acp' })
        // A draft stored before the harness field carries none, and runs on ACP.
        expect(encodeModelChoice({ model: shared, runtime: null })).toEqual(onAcp)
    })

    it('reads the inherit option as no stored default', () => {
        expect(encodeModelChoice({ model: null, runtime: null })).toBeNull()
        expect(decodeModelChoice(null)).toEqual({ model: null, runtime: null })
    })

    // The ACP catalogue owns neither Pi's harness nor its model ids, so deriving an adapter on every
    // save would store a Pi default as a Claude one — a default nobody picked, on a harness the person
    // had moved away from.
    it('saves a Pi default back as Pi, with no adapter', async () => {
        useConfigMocks({ runtime: 'pi', model: 'gpt-5.6-terra', reasoning_effort: 'off' })
        mount()
        await expectLogic(logic)
            .toDispatchActions(['loadMyConfigSuccess'])
            .toMatchValues({ myDraft: { model: 'gpt-5.6-terra', reasoning_effort: 'off', runtime: 'pi' } })

        logic.actions.submitMyDraft()

        await expectLogic(logic).toDispatchActions(['saveMyPreferencesSuccess'])
        expect(posted).toEqual([
            { runtime: 'pi', runtime_adapter: null, model: 'gpt-5.6-terra', reasoning_effort: 'off' },
        ])
    })

    // Every model the picker offers other than the stored Pi one belongs to an ACP adapter, so
    // choosing one is how a person moves their default off Pi from the web.
    it('moves a Pi default onto the ACP harness when an ACP model is picked', async () => {
        useConfigMocks({ runtime: 'pi', model: 'gpt-5.6-terra', reasoning_effort: 'off' })
        mount()
        await expectLogic(logic).toDispatchActions(['loadMyConfigSuccess'])

        logic.actions.setMyDraft({ model: 'claude-opus-5', reasoning_effort: null, runtime: 'acp' })
        logic.actions.submitMyDraft()

        await expectLogic(logic).toDispatchActions(['saveMyPreferencesSuccess'])
        expect(posted).toEqual([
            { runtime: 'acp', runtime_adapter: 'claude', model: 'claude-opus-5', reasoning_effort: null },
        ])
    })

    // Saving the project default refetches the personal config; that load result used to
    // overwrite whatever the person was editing in the other card, and the Save button then
    // read "No changes to save" over the silently discarded pick.
    it('keeps an in-progress personal edit across the refetch a project save triggers', async () => {
        useConfigMocks(null)
        mount()
        await expectLogic(logic).toDispatchActions(['loadMyConfigSuccess'])

        logic.actions.setMyDraft({ model: 'claude-opus-5' })
        logic.actions.setTeamDraft({ model: 'claude-fable-5' })
        logic.actions.submitTeamDraft()

        // Anchor on submitTeamDraft so the matched loadMyConfigSuccess is the refetch,
        // not the mount-time load already in the action history.
        await expectLogic(logic)
            .toDispatchActions(['submitTeamDraft', 'saveTeamPreferencesSuccess', 'loadMyConfigSuccess'])
            .toFinishAllListeners()
            .toMatchValues({
                myDraft: { model: 'claude-opus-5', reasoning_effort: null, runtime: null },
                myDraftDirty: true,
            })
    })
})
