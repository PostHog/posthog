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
import {
    FeatureFlagRulesV2Config,
    FeatureFlagRulesV2DraftExperimentRule,
    FeatureFlagRulesV2DraftRule,
    FeatureFlagType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'
import { moved, newVariant, rulesV2DraftErrors, withEqualWeights } from './featureFlagRulesV2Draft'
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

// A variant split with fields the editor does not render: they must survive a save unchanged.
const SPLIT_RULE = {
    id: 'rule-split',
    rule_type: 'experiment',
    description: 'Layout test',
    targeting: { properties: [] },
    metadata: { owner: 'growth' },
    experiment_id: null,
    paused: false,
    rollout_percentage: 50,
    on_rollout_miss: 'continue',
    assignment_algorithm: 'sha1_60_v1',
    assign_by: 'person',
    seed: 'split-seed',
    variants: [
        { key: 'control', weight: 33.34, value: 'standard' },
        { key: 'compact', weight: 33.33, value: 'compact' },
        { key: 'spacious', weight: 33.33, value: 'spacious' },
    ],
    holdout: { id: null, seed: 'holdout-seed', exclusion_percentage: 5 },
    some_future_field: { kept: true },
}

const STRING_FLAG_RULES = [
    { id: 'rule-beta', rule_type: 'targeted_release', targeting: { properties: [] }, value: 'compact' },
    SPLIT_RULE,
]

const STRING_FLAG = {
    ...NEW_FLAG,
    id: 9,
    key: 'checkout-layout',
    name: 'Checkout layout',
    version: 5,
    filters: {
        version: 2,
        return_type: 'string',
        default_value: null,
        rules: STRING_FLAG_RULES,
    },
} as unknown as FeatureFlagType

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
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/9/`]: () => [200, STRING_FLAG],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    describe('rules v2 editor documents', () => {
        it('echoes stored rule ids and seeds, and sends new rules without either', () => {
            const draft = rulesV2DraftFromFlag(V2_FLAG)
            const body = rulesV2WriteBody({
                ...draft,
                config: { ...draft.config, rules: [...draft.config.rules, NEW_TARGETED_RELEASE_RULE] },
            })

            expect(body.filters.rules.map((rule) => rule.id)).toEqual(['rule-beta', 'rule-rollout', undefined])
            expect(body.filters.rules.map((rule) => ('seed' in rule ? rule.seed : null))).toEqual([
                null,
                'stored-seed',
                null,
            ])
            expect(body).toMatchObject({ key: 'new-checkout', name: 'Checkout redesign', version: 3 })
            expect(body.filters).toMatchObject({ version: 2, return_type: 'boolean', default_value: false })
        })

        it('sends a stored variant split back unchanged, seeds and unrendered fields included', () => {
            const draft = rulesV2DraftFromFlag(STRING_FLAG)
            expect(rulesV2WriteBody(draft).filters).toEqual(STRING_FLAG.filters)
        })

        it('adds the rollout fields when a rule becomes a percentage rollout and drops them when it stops', () => {
            const rule = { ...NEW_TARGETED_RELEASE_RULE, id: 'rule-beta', description: 'Beta users' }
            const rollout = withRuleType(rule, 'percentage_rollout', 'boolean')
            expect(rollout).toEqual({
                ...rule,
                rule_type: 'percentage_rollout',
                rollout_percentage: 0,
                on_rollout_miss: 'continue',
                assignment_algorithm: 'sha1_60_v1',
                assign_by: 'person',
            })
            expect(withRuleType(rollout, 'targeted_release', 'boolean')).toEqual(rule)
        })

        it.each([
            {
                from: 'a targeted release',
                rule: {
                    id: 'rule-beta',
                    rule_type: 'targeted_release',
                    targeting: { properties: [] },
                    value: 'compact',
                },
                rollout: { rollout_percentage: 100, on_rollout_miss: 'continue' },
            },
            {
                from: 'a percentage rollout',
                rule: {
                    id: 'rule-rollout',
                    rule_type: 'percentage_rollout',
                    targeting: { properties: [] },
                    value: 'compact',
                    rollout_percentage: 30,
                    on_rollout_miss: 'return_default',
                    assignment_algorithm: 'sha1_60_v1',
                    seed: 'stored-seed',
                },
                rollout: { rollout_percentage: 30, on_rollout_miss: 'return_default' },
            },
        ] as { from: string; rule: FeatureFlagRulesV2DraftRule; rollout: Record<string, unknown> }[])(
            'turns $from into a variant split with no experiment and no client seed',
            ({ rule, rollout }) => {
                const split = withRuleType(rule, 'experiment', 'string') as FeatureFlagRulesV2DraftExperimentRule
                expect(split).toMatchObject({
                    id: rule.id,
                    rule_type: 'experiment',
                    experiment_id: null,
                    paused: false,
                    assignment_algorithm: 'sha1_60_v1',
                    ...rollout,
                    variants: [
                        { key: 'control', weight: 50, value: 'control' },
                        { key: 'test', weight: 50, value: 'test' },
                    ],
                })
                expect(split).not.toHaveProperty('value')
                expect(split.seed).toBeUndefined()
                expect(split.holdout).toBeUndefined()
            }
        )

        it('turns a variant split into a percentage rollout that keeps its rollout but not its seed', () => {
            const rollout = withRuleType(
                SPLIT_RULE as FeatureFlagRulesV2DraftExperimentRule,
                'percentage_rollout',
                'string'
            )
            expect(rollout).toEqual({
                id: 'rule-split',
                rule_type: 'percentage_rollout',
                description: 'Layout test',
                targeting: { properties: [] },
                metadata: { owner: 'growth' },
                value: '',
                rollout_percentage: 50,
                on_rollout_miss: 'continue',
                assignment_algorithm: 'sha1_60_v1',
                assign_by: 'person',
            })
        })

        // As floats these add up to 100.00000000000001; the server totals them exactly.
        it('accepts weights that total exactly 100 in hundredths', () => {
            const variants = [
                { key: 'control', weight: 64.04, value: 'standard' },
                { key: 'compact', weight: 35.95, value: 'compact' },
                { key: 'spacious', weight: 0.01, value: 'spacious' },
            ]
            const config = STRING_FLAG.filters as FeatureFlagRulesV2Config
            expect(
                rulesV2DraftErrors({ ...config, rules: [{ ...SPLIT_RULE, variants } as FeatureFlagRulesV2DraftRule] })
            ).toEqual({})
        })

        it('adds, moves and removes variants, and distributes their weights to exactly 100', () => {
            const variants = [...SPLIT_RULE.variants, newVariant('string', 3)]
            expect(variants[3]).toEqual({ key: '', weight: 0, value: '' })
            expect(moved(variants, 2, 0).map((variant) => variant.key)).toEqual(['spacious', 'control', 'compact', ''])
            expect(withEqualWeights(variants).map((variant) => variant.weight)).toEqual([25, 25, 25, 25])
            expect(withEqualWeights(variants.slice(0, 3)).map((variant) => variant.weight)).toEqual([
                33.34, 33.33, 33.33,
            ])
            expect(withEqualWeights([...variants, ...variants, ...variants]).map((v) => v.weight)).toEqual([
                ...Array(4).fill(8.34),
                ...Array(8).fill(8.33),
            ])
        })

        it.each([
            [
                { attr: 'key', detail: 'There is already a feature flag with this key.' },
                'key',
                'There is already a feature flag with this key.',
            ],
            [
                { detail: 'filters.rules[1].rollout_percentage: Must be at most 100.' },
                'filters.rules[1].rollout_percentage',
                'Must be at most 100.',
            ],
            [
                { detail: 'filters.rules[0].targeting.properties[0].value: Must be a string.' },
                'filters.rules[0].targeting',
                'filters.rules[0].targeting.properties[0].value: Must be a string.',
            ],
            [
                { detail: 'filters.rules[2].id: Rule ids are server-assigned.' },
                'filters.rules[2]',
                'filters.rules[2].id: Rule ids are server-assigned.',
            ],
            [
                { detail: 'filters.rules[1].variants[2].weight: Must have at most 2 decimal places.' },
                'filters.rules[1].variants[2].weight',
                'Must have at most 2 decimal places.',
            ],
            [
                { detail: 'filters.rules[1].variants[0].key: Variant keys must be unique.' },
                'filters.rules[1].variants[0].key',
                'Variant keys must be unique.',
            ],
            [
                {
                    detail: 'filters.rules[0].variants[1].value: Must be a non-empty string other than $false or $true.',
                },
                'filters.rules[0].variants[1].value',
                'Must be a non-empty string other than $false or $true.',
            ],
            [
                { detail: 'filters.rules[0].variants[1].label: Unknown field.' },
                'filters.rules[0].variants[1]',
                'filters.rules[0].variants[1].label: Unknown field.',
            ],
            [
                { detail: 'filters.rules[0].variants: Variant weights must total exactly 100.' },
                'filters.rules[0].variants',
                'Variant weights must total exactly 100.',
            ],
            [
                { detail: 'filters.rules[3].holdout.exclusion_percentage: Must be between 0 and 100.' },
                'filters.rules[3].holdout.exclusion_percentage',
                'Must be between 0 and 100.',
            ],
            [
                { detail: 'filters.rules[3].holdout.id: Must be null.' },
                'filters.rules[3].holdout',
                'filters.rules[3].holdout.id: Must be null.',
            ],
            [
                { detail: 'filters.rules[3].holdout.seed: Assignment seeds are server-assigned.' },
                'filters.rules[3].holdout.seed',
                'Assignment seeds are server-assigned.',
            ],
            [
                { detail: 'filters.rules[2].seed: Cannot be changed; resetting assignment is a separate operation.' },
                'filters.rules[2].seed',
                'Cannot be changed; resetting assignment is a separate operation.',
            ],
            [
                { detail: 'filters.rules[2].paused: Must be true or false.' },
                'filters.rules[2].paused',
                'Must be true or false.',
            ],
            [
                { detail: 'filters.rules[2].experiment_id: Linking an experiment is not available yet.' },
                'filters.rules[2]',
                'filters.rules[2].experiment_id: Linking an experiment is not available yet.',
            ],
            [
                { detail: 'filters.return_type: Cannot be changed after the flag is created.' },
                'filters.return_type',
                'Cannot be changed after the flag is created.',
            ],
            [
                { detail: 'filters: This flag cannot be updated through this API.' },
                null,
                'filters: This flag cannot be updated through this API.',
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

    it('creates a string flag with a variant split that carries no seed and no experiment', async () => {
        const create = jest.spyOn(api, 'create').mockResolvedValue({ ...STRING_FLAG, id: 10 })
        const logic = featureFlagRulesV2EditorLogic({ id: 'new' })
        logic.mount()

        logic.actions.setDraft({ key: 'checkout-layout' })
        logic.actions.setReturnType('string')
        logic.actions.addRule()
        expect(logic.values.draft.config).toMatchObject({ return_type: 'string', default_value: null })
        expect(logic.values.saveDisabledReason).toBe('Rule 1: Enter a value.')
        logic.actions.updateRule(0, withRuleType(logic.values.draft.config.rules[0], 'experiment', 'string'))
        logic.actions.updateRule(0, {
            ...(logic.values.draft.config.rules[0] as FeatureFlagRulesV2DraftExperimentRule),
            paused: true,
            holdout: { id: null, exclusion_percentage: 10 },
        })
        expect(logic.values.saveDisabledReason).toBeNull()
        await expectLogic(logic, () => logic.actions.saveRulesV2Flag())
            .toDispatchActions(['saveRulesV2FlagSuccess'])
            .toFinishAllListeners()

        const body = create.mock.calls[0][1] as Record<string, any>
        expect(body.filters).toEqual({
            version: 2,
            return_type: 'string',
            default_value: null,
            rules: [
                {
                    rule_type: 'experiment',
                    targeting: { properties: [] },
                    experiment_id: null,
                    paused: true,
                    rollout_percentage: 100,
                    on_rollout_miss: 'continue',
                    assignment_algorithm: 'sha1_60_v1',
                    assign_by: 'person',
                    variants: [
                        { key: 'control', weight: 50, value: 'control' },
                        { key: 'test', weight: 50, value: 'test' },
                    ],
                    holdout: { id: null, exclusion_percentage: 10 },
                },
            ],
        })
        expect(JSON.stringify(body)).not.toContain('seed')
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
            const [stored0, stored1] = (V2_FLAG.filters as FeatureFlagRulesV2Config).rules
            expect(body.filters.rules).toEqual([stored1, stored0])
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
                detail: 'filters.rules[1].rollout_percentage: Must be at most 100.',
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
    describe('editing a variant split', () => {
        let logic: ReturnType<typeof featureFlagRulesV2EditorLogic.build>

        const split = (): FeatureFlagRulesV2DraftExperimentRule =>
            logic.values.draft.config.rules[1] as FeatureFlagRulesV2DraftExperimentRule
        const setSplit = (fields: Partial<FeatureFlagRulesV2DraftExperimentRule>): void =>
            logic.actions.updateRule(1, { ...split(), ...fields })
        const setVariant = (index: number, fields: Record<string, unknown>): void =>
            setSplit({ variants: split().variants.map((v, i) => (i === index ? { ...v, ...fields } : v)) })

        beforeEach(async () => {
            const pageLogic = featureFlagLogic({ id: 9 })
            pageLogic.mount()
            await expectLogic(pageLogic, () => pageLogic.actions.editFeatureFlag(true))
                .toDispatchActions(['loadFeatureFlagSuccess'])
                .toFinishAllListeners()
            logic = featureFlagRulesV2EditorLogic({ id: 9 })
            logic.mount()
        })

        it('changes another rule and moves the split without touching any field of the split', async () => {
            const update = jest.spyOn(api, 'update').mockResolvedValue({ ...STRING_FLAG, version: 6 })

            logic.actions.updateRule(0, { ...STRING_FLAG_RULES[0], value: 'spacious' } as FeatureFlagRulesV2DraftRule)
            logic.actions.moveRule(1, 0)
            await expectLogic(logic, () => logic.actions.saveRulesV2Flag())
                .toDispatchActions(['saveRulesV2FlagSuccess'])
                .toFinishAllListeners()

            const body = update.mock.calls[0][1] as Record<string, any>
            expect(body.version).toBe(5)
            expect(body.filters.rules).toEqual([
                SPLIT_RULE,
                { id: 'rule-beta', rule_type: 'targeted_release', targeting: { properties: [] }, value: 'spacious' },
            ])
        })

        it('edits variants and the holdout, echoing both seeds and keeping fields it does not show', async () => {
            const update = jest.spyOn(api, 'update').mockResolvedValue({ ...STRING_FLAG, version: 6 })

            setSplit({ variants: moved(split().variants, 2, 0) })
            setSplit({ variants: split().variants.filter((variant) => variant.key !== 'compact') })
            setVariant(0, { weight: 50 })
            setVariant(1, { weight: 50 })
            setSplit({ holdout: { ...split().holdout!, exclusion_percentage: 7.5 }, paused: true })
            await expectLogic(logic, () => logic.actions.saveRulesV2Flag())
                .toDispatchActions(['saveRulesV2FlagSuccess'])
                .toFinishAllListeners()

            const sent = (update.mock.calls[0][1] as Record<string, any>).filters.rules[1]
            expect(sent).toEqual({
                ...SPLIT_RULE,
                paused: true,
                variants: [
                    { key: 'spacious', weight: 50, value: 'spacious' },
                    { key: 'control', weight: 50, value: 'standard' },
                ],
                holdout: { id: null, seed: 'holdout-seed', exclusion_percentage: 7.5 },
            })
        })

        it('removes the holdout with its seed, and adds one back without a seed', () => {
            const { holdout: _holdout, ...withoutHoldout } = split()
            logic.actions.updateRule(1, withoutHoldout)
            expect(split()).not.toHaveProperty('holdout')

            setSplit({ holdout: { id: null, exclusion_percentage: 10 } })
            expect(rulesV2WriteBody(logic.values.draft).filters.rules[1]).toMatchObject({
                seed: 'split-seed',
                holdout: { id: null, exclusion_percentage: 10 },
            })
            expect(JSON.stringify(split().holdout)).not.toContain('seed')
        })

        it.each([
            {
                check: 'weights that do not total 100',
                edit: () => setVariant(0, { weight: 23.34 }),
                field: 'filters.rules[1].variants',
                error: 'Variant weights must total 100% (now 90%).',
            },
            {
                check: 'a weight with three decimal places',
                edit: () => setVariant(1, { weight: 33.333 }),
                field: 'filters.rules[1].variants[1].weight',
                error: 'Must have at most two decimal places.',
            },
            {
                check: 'a duplicate key',
                edit: () => setVariant(2, { key: 'control' }),
                field: 'filters.rules[1].variants[2].key',
                error: 'Variant keys must be unique.',
            },
            {
                check: 'a key with a dot',
                edit: () => setVariant(2, { key: 'layout.v2' }),
                field: 'filters.rules[1].variants[2].key',
                error: 'Only letters, numbers, hyphens (-) and underscores (_) are allowed.',
            },
            {
                check: 'an empty key',
                edit: () => setVariant(2, { key: '' }),
                field: 'filters.rules[1].variants[2].key',
                error: 'Enter a key.',
            },
            {
                check: 'an empty string value',
                edit: () => setVariant(0, { value: '' }),
                field: 'filters.rules[1].variants[0].value',
                error: 'Enter a value.',
            },
            {
                check: 'a value of another type',
                edit: () => setVariant(0, { value: true }),
                field: 'filters.rules[1].variants[0].value',
                error: 'Enter a value.',
            },
            {
                check: 'a single variant',
                edit: () => setSplit({ variants: [{ key: 'control', weight: 100, value: 'standard' }] }),
                field: 'filters.rules[1].variants',
                error: 'Add at least 2 variants.',
            },
            {
                check: 'a holdout above 100%',
                edit: () => setSplit({ holdout: { id: null, exclusion_percentage: 101 } }),
                field: 'filters.rules[1].holdout.exclusion_percentage',
                error: 'Must be between 0 and 100.',
            },
        ])('flags $check against its field and blocks the save', ({ edit, field, error }) => {
            expect(logic.values.saveDisabledReason).toBeNull()
            edit()
            expect(logic.values.fieldError(field)).toBe(error)
            expect(logic.values.saveDisabledReason).toBe(`Rule 2: ${error}`)
        })

        it('shows a server error on the variant field it names', async () => {
            jest.spyOn(api, 'update').mockRejectedValue({
                status: 400,
                detail: 'filters.rules[1].variants[2].value: Must be a non-empty string other than $false or $true.',
            })

            await expectLogic(logic, () => logic.actions.saveRulesV2Flag()).toDispatchActions([
                'saveRulesV2FlagFailure',
            ])
            expect(logic.values.fieldError('filters.rules[1].variants[2].value')).toBe(
                'Must be a non-empty string other than $false or $true.'
            )
        })
    })
})
