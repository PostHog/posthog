import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'
import {
    NEW_TARGETED_RELEASE_RULE,
    featureFlagRulesV2EditorLogic,
    rulesV2DraftFromFlag,
    rulesV2SaveError,
    rulesV2WriteBody,
    withRuleType,
} from './featureFlagRulesV2EditorLogic'

jest.mock('~/layout/panel-layout/ProjectTree/projectTreeLogic', () => ({
    ...jest.requireActual('~/layout/panel-layout/ProjectTree/projectTreeLogic'),
    refreshTreeItem: jest.fn(),
}))

const V2_FLAG = {
    ...NEW_FLAG,
    id: 7,
    key: 'new-checkout',
    name: 'Checkout redesign',
    version: 3,
    filters: {
        version: 2,
        return_type: 'boolean',
        default_value: false,
        rules: [
            {
                id: 'rule-beta',
                rule_type: 'targeted_release',
                targeting: { properties: [{ key: 'plan', type: 'person', operator: 'exact', value: ['beta'] }] },
                value: true,
            },
            {
                id: 'rule-rollout',
                rule_type: 'percentage_rollout',
                description: 'Everyone else',
                targeting: { properties: [] },
                value: true,
                rollout_percentage: 20,
                on_rollout_miss: 'return_default',
                assignment_algorithm: 'sha1_60_v1',
                assign_by: 'person',
                seed: 'stored-seed',
            },
        ],
    },
} as unknown as FeatureFlagType

describe('featureFlagRulesV2EditorLogic', () => {
    beforeEach(() => {
        silenceKeaLoadersErrors()
        useMocks({
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/7/`]: () => [200, V2_FLAG],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    describe('rules v2 editor documents', () => {
        it('keeps stored rule ids, never holds a seed, and sends new rules without an id', () => {
            const draft = rulesV2DraftFromFlag(V2_FLAG)
            const body = rulesV2WriteBody({
                ...draft,
                config: { ...draft.config, rules: [...draft.config.rules, NEW_TARGETED_RELEASE_RULE] },
            })

            expect(body.filters.rules.map((rule) => rule.id)).toEqual(['rule-beta', 'rule-rollout', undefined])
            expect(JSON.stringify(body)).not.toContain('seed')
            expect(body).toMatchObject({ key: 'new-checkout', name: 'Checkout redesign', version: 3 })
            expect(body.filters).toMatchObject({ version: 2, return_type: 'boolean', default_value: false })
        })

        it('adds the rollout fields when a rule becomes a percentage rollout and drops them when it stops', () => {
            const rule = { ...NEW_TARGETED_RELEASE_RULE, id: 'rule-beta', description: 'Beta users' }
            const rollout = withRuleType(rule, 'percentage_rollout')
            expect(rollout).toEqual({
                ...rule,
                rule_type: 'percentage_rollout',
                rollout_percentage: 0,
                on_rollout_miss: 'continue',
                assignment_algorithm: 'sha1_60_v1',
                assign_by: 'person',
            })
            expect(withRuleType(rollout, 'targeted_release')).toEqual(rule)
        })

        it.each([
            [
                { attr: 'key', detail: 'There is already a feature flag with this key.' },
                'key',
                'There is already a feature flag with this key.',
            ],
            [
                { attr: 'filters__rules__1__rollout_percentage', detail: 'Must be at most 100.' },
                'filters.rules[1].rollout_percentage',
                'Must be at most 100.',
            ],
            [
                { attr: 'filters__rules__0__targeting__properties__0__value', detail: 'Must be a string.' },
                'filters.rules[0].targeting',
                'filters.rules[0].targeting.properties[0].value: Must be a string.',
            ],
            [
                { attr: 'filters__rules__2__id', detail: 'Rule ids are server-assigned.' },
                'filters.rules[2]',
                'filters.rules[2].id: Rule ids are server-assigned.',
            ],
            [
                { attr: 'filters__default_value', detail: 'Must be true or false.' },
                'filters.default_value',
                'Must be true or false.',
            ],
            [
                { attr: 'filters__rules', detail: 'At most 100 rules are allowed.' },
                null,
                'At most 100 rules are allowed.',
            ],
            [
                { attr: 'tags', detail: 'Add at least one tag. This project requires new feature flags to be tagged.' },
                'tags',
                'Add at least one tag. This project requires new feature flags to be tagged.',
            ],
            [
                { attr: 'active', detail: 'A flag with this configuration format is created disabled.' },
                null,
                'A flag with this configuration format is created disabled.',
            ],
            [
                { detail: 'This flag cannot be written while an approval policy is enabled.' },
                null,
                'This flag cannot be written while an approval policy is enabled.',
            ],
        ])('maps %j to the field that owns it', (error, field, message) => {
            expect(rulesV2SaveError(error)).toEqual({ field, message })
        })
    })

    it('creates without a row version and lands on the new flag', async () => {
        const create = jest.spyOn(api, 'create').mockResolvedValue({ ...V2_FLAG, id: 8 })
        const logic = featureFlagRulesV2EditorLogic({ id: 'new' })
        logic.mount()

        logic.actions.setDraft({ key: 'new-checkout', tags: ['checkout'] })
        logic.actions.addRule()
        await expectLogic(logic, () => logic.actions.saveRulesV2Flag())
            .toDispatchActions(['saveRulesV2FlagSuccess'])
            .toFinishAllListeners()

        const body = create.mock.calls[0][1] as Record<string, any>
        expect(body).not.toHaveProperty('version')
        expect(body).not.toHaveProperty('active')
        expect(body.tags).toEqual(['checkout'])
        expect(body.filters.rules).toEqual([NEW_TARGETED_RELEASE_RULE])
        expect(router.values.location.pathname).toContain(urls.featureFlag(8))
        expect(refreshTreeItem).toHaveBeenCalledWith('feature_flag', '8')
    })

    it('blocks a create in a project that requires evaluation contexts, which a rules v2 create cannot set', () => {
        enabledFeaturesLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.FLAG_EVALUATION_TAGS]: true })
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, require_evaluation_contexts: true })
        const logic = featureFlagRulesV2EditorLogic({ id: 'new' })
        logic.mount()

        logic.actions.setDraft({ key: 'new-checkout' })
        expect(logic.values.saveDisabledReason).toContain('requires evaluation contexts')
    })

    describe('editing a stored flag', () => {
        let logic: ReturnType<typeof featureFlagRulesV2EditorLogic.build>

        let pageLogic: ReturnType<typeof featureFlagLogic.build>

        beforeEach(async () => {
            // The editor mounts once the flag page has loaded the row and entered edit mode.
            pageLogic = featureFlagLogic({ id: 7 })
            pageLogic.mount()
            await expectLogic(pageLogic, () => pageLogic.actions.editFeatureFlag(true))
                .toDispatchActions(['loadFeatureFlagSuccess'])
                .toFinishAllListeners()
            logic = featureFlagRulesV2EditorLogic({ id: 7 })
            logic.mount()
        })

        it('replaces the whole document, carries the row version and shows the saved flag', async () => {
            const update = jest.spyOn(api, 'update').mockResolvedValue({ ...V2_FLAG, version: 4 })

            const [firstKey, secondKey] = logic.values.ruleKeys
            logic.actions.moveRule(1, 0)
            expect(logic.values.ruleKeys).toEqual([secondKey, firstKey])
            await expectLogic(logic, () => logic.actions.saveRulesV2Flag())
                .toDispatchActions(['saveRulesV2FlagSuccess', 'loadFeatureFlagSuccess', 'editFeatureFlag'])
                .toNotHaveDispatchedActions(['loadFeatureFlag'])
                .toFinishAllListeners()

            const body = update.mock.calls[0][1] as Record<string, any>
            expect(body.version).toBe(3)
            expect(body.filters.rules.map((rule: { id: string }) => rule.id)).toEqual(['rule-rollout', 'rule-beta'])
            expect(JSON.stringify(body)).not.toContain('seed')
            expect(refreshTreeItem).toHaveBeenCalledWith('feature_flag', '7')
            expect(pageLogic.values).toMatchObject({ isEditingFlag: false, featureFlag: { version: 4 } })
        })

        it.each([
            {
                edit: 'a rule move',
                confirmation: true,
                dialog: 'Confirm changes to feature flag "new-checkout"?',
                apply: () => logic.actions.moveRule(1, 0),
            },
            {
                edit: 'a name change',
                confirmation: true,
                dialog: null,
                apply: () => logic.actions.setDraft({ name: 'Renamed' }),
            },
            {
                edit: 'a key change',
                confirmation: false,
                dialog: 'Change flag key?',
                apply: () => logic.actions.setDraft({ key: 'checkout-v2' }),
            },
        ])('with project confirmation $confirmation, $edit asks $dialog', async ({ confirmation, dialog, apply }) => {
            teamLogic.actions.loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                feature_flag_confirmation_enabled: confirmation,
            })
            const openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
            const update = jest.spyOn(api, 'update').mockResolvedValue({ ...V2_FLAG, version: 4 })

            apply()
            logic.actions.saveRulesV2Flag()
            expect(openDialog.mock.calls.map(([props]) => props.title)).toEqual(dialog ? [dialog] : [])
            if (dialog) {
                expect(update).not.toHaveBeenCalled()
                openDialog.mock.calls[0][0].primaryButton?.onClick?.(undefined as any)
            }
            await expectLogic(logic).toDispatchActions(['saveRulesV2FlagSuccess']).toFinishAllListeners()
            expect(update).toHaveBeenCalledTimes(1)
        })

        it('does not save a key change whose confirmation is cancelled', async () => {
            const openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
            const update = jest.spyOn(api, 'update')

            logic.actions.setDraft({ key: 'checkout-v2' })
            logic.actions.saveRulesV2Flag()
            expect(openDialog.mock.calls.map(([props]) => props.title)).toEqual(['Change flag key?'])
            openDialog.mock.calls[0][0].onAfterClose?.()
            await expectLogic(logic).toFinishAllListeners()

            expect(update).not.toHaveBeenCalled()
            expect(logic.values.saving).toBe(false)
        })

        it('saves with the version its draft was loaded from, even after the page refreshed underneath', async () => {
            const update = jest.spyOn(api, 'update').mockResolvedValue({ ...V2_FLAG, version: 6 })
            // A background refresh (for example after an AI change) replaces the page's flag while the draft is open.
            featureFlagLogic({ id: 7 }).actions.setFeatureFlag({ ...V2_FLAG, version: 5 })

            await expectLogic(logic, () => logic.actions.saveRulesV2Flag())
                .toDispatchActions(['saveRulesV2FlagSuccess'])
                .toFinishAllListeners()

            expect((update.mock.calls[0][1] as Record<string, any>).version).toBe(3)
        })

        it('asks before navigating away from unsaved edits, and not after saving', async () => {
            const confirm = jest.spyOn(window, 'confirm').mockReturnValue(false)
            expect(logic.values.hasUnsavedChanges).toBe(false)

            logic.actions.setConfig({ default_value: null })
            router.actions.push(urls.featureFlags())
            expect(confirm).toHaveBeenCalledTimes(1)

            jest.spyOn(api, 'update').mockResolvedValue({ ...V2_FLAG, version: 4 })
            await expectLogic(logic, () => logic.actions.saveRulesV2Flag())
                .toDispatchActions(['saveRulesV2FlagSuccess'])
                .toFinishAllListeners()
            expect(logic.values.hasUnsavedChanges).toBe(false)
        })

        it('keeps unsaved edits when the flag page URL is pushed again', async () => {
            router.actions.push(urls.featureFlag(7))
            await expectLogic(pageLogic).toDispatchActions(['loadFeatureFlagSuccess']).toFinishAllListeners()
            pageLogic.actions.editFeatureFlag(true)

            logic.actions.setConfig({ default_value: null })
            // The project-prefixed path passes the editor's unload prompt, so only featureFlagLogic's guard keeps the draft.
            await expectLogic(pageLogic, () => router.actions.push(router.values.location.pathname))
                .toFinishAllListeners()
                .toMatchValues({ isEditingFlag: true })
            expect(logic.values.draft.config.default_value).toBeNull()

            // Cancel leaves the draft dirty, so closing the editor is what lets later pushes reach the page.
            expect(pageLogic.values.rulesV2DraftDirty).toBe(true)
            logic.unmount()
            expect(pageLogic.values.rulesV2DraftDirty).toBe(false)
        })

        it.each([
            {
                condition: 'an exact match with no value',
                operator: PropertyOperator.Exact,
                value: null,
                reason: 'Choose a value for every condition in rule 2.',
            },
            {
                condition: 'an exact match with every value removed',
                operator: PropertyOperator.Exact,
                value: [],
                reason: 'Choose a value for every condition in rule 2.',
            },
            {
                condition: 'a membership check with no values',
                operator: PropertyOperator.In,
                value: [],
                reason: 'Choose a value for every condition in rule 2.',
            },
            { condition: 'an is-set check', operator: PropertyOperator.IsSet, value: null, reason: null },
            { condition: 'an is-not-set check', operator: PropertyOperator.IsNotSet, value: null, reason: null },
        ])('with $condition, the save guard says $reason', ({ operator, value, reason }) => {
            const rule = logic.values.draft.config.rules[1]
            logic.actions.updateRule(1, {
                ...rule,
                targeting: { properties: [{ key: 'email', type: PropertyFilterType.Person, operator, value }] },
            })
            expect(logic.values.saveDisabledReason).toBe(reason)
        })

        it.each([
            { key: '', reason: 'Please set a key' },
            { key: 'a'.repeat(401), reason: 'Key must be 400 characters or less.' },
        ])('with the key $key.length characters long, the save guard says $reason', ({ key, reason }) => {
            logic.actions.setDraft({ key })
            expect(logic.values.saveDisabledReason).toBe(reason)
        })

        it('saves a stored flag in a project that requires evaluation contexts, which only a create must set', () => {
            enabledFeaturesLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.FLAG_EVALUATION_TAGS]: true })
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, require_evaluation_contexts: true })

            logic.actions.setDraft({ name: 'Renamed' })
            expect(logic.values.saveDisabledReason).toBeNull()
        })

        it('shows a validation error against its field and in a toast, and clears it on the next edit', async () => {
            const toastError = jest.spyOn(lemonToast, 'error')
            jest.spyOn(api, 'update').mockRejectedValue({
                status: 400,
                attr: 'filters__rules__1__rollout_percentage',
                detail: 'Must be at most 100.',
            })

            await expectLogic(logic, () => logic.actions.saveRulesV2Flag())
                .toDispatchActions(['saveRulesV2FlagFailure'])
                .toMatchValues({
                    saveError: { field: 'filters.rules[1].rollout_percentage', message: 'Must be at most 100.' },
                    saving: false,
                })
            expect(toastError).toHaveBeenCalledWith('Flag not saved: Must be at most 100.')

            logic.actions.updateRule(1, { ...logic.values.draft.config.rules[1] })
            expect(logic.values).toMatchObject({
                hasUnsavedChanges: false,
                saveError: { message: 'Must be at most 100.' },
            })

            logic.actions.setConfig({ default_value: null })
            expect(logic.values.saveError).toBeNull()
        })

        it('reloads the flag and leaves the editor when the row version is stale', async () => {
            jest.spyOn(api, 'update').mockRejectedValue({ status: 409, detail: 'This feature flag has changed.' })
            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/7/`]: () => [
                        200,
                        { ...V2_FLAG, name: 'Renamed elsewhere', version: 4 },
                    ],
                },
            })

            await expectLogic(logic, () => logic.actions.saveRulesV2Flag()).toDispatchActions([
                'editFeatureFlag',
                'refreshFeatureFlag',
            ])
            await expectLogic(pageLogic).toDispatchActions(['refreshFeatureFlagSuccess']).toFinishAllListeners()
            expect(logic.values).toMatchObject({ saveError: null, saving: false })
            expect(pageLogic.values).toMatchObject({
                isEditingFlag: false,
                featureFlag: { name: 'Renamed elsewhere', version: 4 },
            })
        })
    })
})
