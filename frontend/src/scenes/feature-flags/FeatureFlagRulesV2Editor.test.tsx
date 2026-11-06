import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { FeatureFlagRulesV2DraftExperimentRule, FeatureFlagRulesV2DraftRule } from '~/types'

import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagRulesV2Editor } from './FeatureFlagRulesV2Editor'
import { featureFlagRulesV2EditorLogic } from './featureFlagRulesV2EditorLogic'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

jest.mock('./JSONEditorInput', () => ({
    JSONEditorInput: ({ value, onChange }: { value: string; onChange: (value: string) => void }): JSX.Element => (
        <textarea value={value} onChange={(event) => onChange(event.target.value)} />
    ),
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
                description: 'Beta users',
                targeting: { properties: [] },
                value: true,
            },
            {
                id: 'rule-rollout',
                rule_type: 'percentage_rollout',
                description: 'Everyone else',
                targeting: { properties: [] },
                value: true,
                rollout_percentage: 20,
                on_rollout_miss: 'continue',
                assignment_algorithm: 'sha1_60_v1',
                assign_by: 'person',
                seed: 'stored-seed',
            },
        ],
    },
}

const STRING_EXPERIMENT_FLAG = {
    ...NEW_FLAG,
    id: 9,
    key: 'checkout-layout',
    version: 5,
    filters: {
        version: 2,
        return_type: 'string',
        default_value: null,
        rules: [
            {
                id: 'rule-split',
                rule_type: 'experiment',
                targeting: { properties: [] },
                paused: false,
                rollout_percentage: 50,
                on_rollout_miss: 'continue',
                assignment_algorithm: 'sha1_60_v1',
                seed: 'split-seed',
                variants: [
                    { key: 'control', weight: 50, value: 'standard' },
                    { key: 'compact', weight: 50, value: 'compact' },
                ],
                holdout: { seed: 'holdout-seed', exclusion_percentage: 5 },
            },
        ],
    },
}

const OBJECT_FLAG = {
    ...NEW_FLAG,
    id: 11,
    key: 'checkout-config',
    version: 2,
    filters: {
        version: 2,
        return_type: 'object',
        default_value: { columns: 1 },
        rules: [
            {
                id: 'rule-beta',
                rule_type: 'targeted_release',
                targeting: { properties: [] },
                value: { columns: 2 },
            },
        ],
    },
}

const NUMBER_FLAG = {
    ...OBJECT_FLAG,
    id: 12,
    key: 'checkout-limit',
    filters: {
        version: 2,
        return_type: 'number',
        default_value: 10,
        rules: [{ id: 'rule-beta', rule_type: 'targeted_release', targeting: { properties: [] }, value: 25 }],
    },
}

async function renderEditor(id: number): Promise<void> {
    const pageLogic = featureFlagLogic({ id })
    pageLogic.mount()
    await expectLogic(pageLogic).toDispatchActions(['loadFeatureFlagSuccess']).toFinishAllListeners()
    render(
        <Provider>
            <FeatureFlagRulesV2Editor id={id} />
        </Provider>
    )
}

describe('FeatureFlagRulesV2Editor', () => {
    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/feature_flags/7/': V2_FLAG,
                '/api/projects/:team/feature_flags/9/': STRING_EXPERIMENT_FLAG,
                '/api/projects/:team/feature_flags/11/': OBJECT_FLAG,
                '/api/projects/:team/feature_flags/12/': NUMBER_FLAG,
                '/api/projects/:team/feature_flags/:id/status': { status: 'active', reason: 'mock reason' },
            },
            post: {
                '/api/projects/:team/feature_flags/user_blast_radius': () => [200, { affected: 120, total: 2000 }],
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    describe('a boolean flag', () => {
        beforeEach(async () => {
            await renderEditor(7)
        })

        const rules = (): FeatureFlagRulesV2DraftRule[] =>
            featureFlagRulesV2EditorLogic({ id: 7 }).values.draft.config.rules
        const openRuleMenu = (index: number): void => {
            fireEvent.click(screen.getByLabelText(`Rule ${index + 1} actions`))
        }

        it('names each text input by its label', () => {
            expect(screen.getByLabelText('Flag key')).toHaveValue('new-checkout')
            expect(screen.getByLabelText(/^Description/).tagName).toBe('TEXTAREA')
            expect(screen.getByLabelText('Rule 1 description')).toHaveValue('Beta users')
            expect(screen.getByLabelText('Rule 2 description')).toHaveValue('Everyone else')
            expect(screen.getByLabelText('Rollout percentage')).toHaveValue('20')
            const secondRule = screen.getByLabelText('Rule 2')
            expect(secondRule).toHaveAttribute('role', 'group')
            expect(within(secondRule).getByLabelText('Rollout percentage')).toHaveValue('20')
        })

        it('offers only true and false as the default value', () => {
            const defaultValue = within(screen.getByLabelText('Default value'))
            expect(defaultValue.getAllByRole('button').map((button) => button.textContent)).toEqual(['true', 'false'])
        })

        it('does not count a click on the selected default as an edit', () => {
            fireEvent.click(within(screen.getByLabelText('Default value')).getByText('false'))
            expect(featureFlagRulesV2EditorLogic({ id: 7 }).values.hasUnsavedChanges).toBe(false)
        })

        it("keeps a saved flag's value type on a click or an arrow key", () => {
            fireEvent.click(document.querySelector<HTMLElement>('[data-attr="rules-v2-return-type-string"]')!)
            fireEvent.keyDown(screen.getByLabelText('Value type'), { key: 'ArrowRight' })
            expect(featureFlagRulesV2EditorLogic({ id: 7 }).values.draft.config).toMatchObject({
                return_type: 'boolean',
                default_value: false,
            })
        })

        it('estimates how many users each rule matches and its rollout reaches', async () => {
            const [, rolloutRule] = document.querySelectorAll('[data-attr="rules-v2-rule"]')
            await waitFor(() => expect(rolloutRule).toHaveTextContent('≈ 120 users'))
            expect(rolloutRule).toHaveTextContent('≈ 24 users')
        })

        it('warns that a rule after a rule claiming everyone is never reached, until it moves up', async () => {
            const [beta, rollout] = document.querySelectorAll('[data-attr="rules-v2-rule"]')
            expect(beta.querySelector('[data-attr="rules-v2-rule-unreachable"]')).toBeNull()
            expect(rollout.querySelector('[data-attr="rules-v2-rule-unreachable"]')).toHaveTextContent(
                'rule 1 already decides the value'
            )

            openRuleMenu(1)
            fireEvent.click(await screen.findByText('Move up'))

            await waitFor(() => expect(rules().map((rule) => rule.id)).toEqual(['rule-rollout', 'rule-beta']))
            expect(document.querySelector('[data-attr="rules-v2-rule-unreachable"]')).toBeNull()
            await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('Rule 1 actions')))
        })

        it('moves focus to Add rule after deleting a rule, since its card is gone', async () => {
            openRuleMenu(1)
            fireEvent.click(await screen.findByText('Delete rule'))

            expect(rules().map((rule) => rule.id)).toEqual(['rule-beta'])
            await waitFor(() =>
                expect(document.activeElement).toBe(
                    document.querySelector<HTMLElement>('[data-attr="rules-v2-add-rule"]')
                )
            )
        })

        it('leaves a clean draft on Cancel without asking', async () => {
            featureFlagLogic({ id: 7 }).actions.editFeatureFlag(true)
            fireEvent.click(screen.getByText('Cancel'))

            await waitFor(() => expect(featureFlagLogic({ id: 7 }).values.isEditingFlag).toBe(false))
            expect(screen.queryByText('Discard your changes?')).toBeNull()
        })

        it('asks before Cancel discards unsaved edits', async () => {
            featureFlagLogic({ id: 7 }).actions.editFeatureFlag(true)
            fireEvent.change(screen.getByLabelText('Rule 1 description'), { target: { value: 'Beta testers' } })
            fireEvent.click(screen.getByText('Cancel'))

            expect(await screen.findByText('Discard your changes?')).toBeInTheDocument()
            expect(featureFlagLogic({ id: 7 }).values.isEditingFlag).toBe(true)
            fireEvent.click(screen.getByText('Discard changes'))
            await waitFor(() => expect(featureFlagLogic({ id: 7 }).values.isEditingFlag).toBe(false))
        })

        it('adds a rule of the type picked from the add menu', async () => {
            fireEvent.click(document.querySelector<HTMLElement>('[data-attr="rules-v2-add-rule"]')!)
            fireEvent.click(await screen.findByText('Percentage rollout', { selector: '.font-semibold' }))

            expect(rules()).toHaveLength(3)
            expect(rules()[2]).toEqual({
                rule_type: 'percentage_rollout',
                targeting: { properties: [] },
                value: true,
                rollout_percentage: 0,
                on_rollout_miss: 'continue',
                assignment_algorithm: 'sha1_60_v1',
                assign_by: 'person',
            })
        })

        it('duplicates a rule below itself without its id or seed', async () => {
            openRuleMenu(1)
            fireEvent.click(await screen.findByText('Duplicate'))

            const { id: _id, seed: _seed, ...copy } = V2_FLAG.filters.rules[1]
            expect(rules().map((rule) => rule.id)).toEqual(['rule-beta', 'rule-rollout', undefined])
            expect(rules()[2]).toEqual(copy)
            await waitFor(() => expect(screen.getByLabelText('Rule 3 description')).toHaveValue('Everyone else'))
        })
    })

    describe('an experiment rule', () => {
        const experimentRule = (): FeatureFlagRulesV2DraftExperimentRule =>
            featureFlagRulesV2EditorLogic({ id: 9 }).values.draft.config
                .rules[0] as FeatureFlagRulesV2DraftExperimentRule
        const click = (dataAttr: string, index = 0): void => {
            fireEvent.click(document.querySelectorAll<HTMLElement>(`[data-attr="${dataAttr}"]`)[index])
        }

        beforeEach(async () => {
            await renderEditor(9)
        })

        it('estimates the reach of an experiment rule net of its holdout', async () => {
            const [rule] = document.querySelectorAll('[data-attr="rules-v2-rule"]')
            await waitFor(() => expect(rule).toHaveTextContent('≈ 120 users'))
            expect(rule).toHaveTextContent('≈ 57 users')
        })

        it('keeps a variant value that differs from its key when the key is renamed', () => {
            fireEvent.change(screen.getByLabelText('Variant 1 key'), { target: { value: 'baseline' } })
            expect(screen.getByLabelText('Variant 1 value')).toHaveValue('standard')
        })

        it('stores a cleared string default as null', () => {
            fireEvent.change(screen.getByLabelText('Default value'), { target: { value: 'standard' } })
            expect(featureFlagRulesV2EditorLogic({ id: 9 }).values.draft.config.default_value).toBe('standard')
            fireEvent.change(screen.getByLabelText('Default value'), { target: { value: '' } })
            expect(featureFlagRulesV2EditorLogic({ id: 9 }).values.draft.config.default_value).toBeNull()
        })

        it('labels every variant input and shows no seed', () => {
            expect(screen.getByLabelText('Variant 1 key')).toHaveValue('control')
            expect(screen.getByLabelText('Variant 2 value')).toHaveValue('compact')
            expect(screen.getByLabelText('Variant 2 weight')).toHaveValue('50')
            expect(screen.getByLabelText('Holdout excludes')).toHaveValue('5')
            expect(screen.getByLabelText('Rollout percentage')).toHaveValue('50')
            expect(document.body).not.toHaveTextContent(/split-seed|holdout-seed/)
            expect(document.body.innerHTML).not.toMatch(/split-seed|holdout-seed/)
        })

        it('adds, moves and removes variants and distributes their weights', async () => {
            click('rules-v2-add-variant')
            fireEvent.change(screen.getByLabelText('Variant 3 key'), { target: { value: 'spacious' } })
            await waitFor(() => expect(screen.getByLabelText('Variant 3 value')).toHaveValue('spacious'))
            click('rules-v2-distribute-weights')
            click('rules-v2-move-variant-up', 2)
            click('rules-v2-remove-variant', 0)

            expect(experimentRule().variants).toEqual([
                { key: 'spacious', weight: 33.33, value: 'spacious' },
                { key: 'compact', weight: 33.33, value: 'compact' },
            ])
            expect(experimentRule()).toMatchObject({ seed: 'split-seed', holdout: { seed: 'holdout-seed' } })
        })

        it('pauses the experiment rule, removes its holdout and adds a new one', async () => {
            click('rules-v2-experiment-paused')
            click('rules-v2-experiment-holdout')

            expect(experimentRule()).toMatchObject({ paused: true })
            expect(experimentRule()).not.toHaveProperty('holdout')
            expect(screen.queryByLabelText('Holdout excludes')).not.toBeInTheDocument()

            click('rules-v2-experiment-holdout')
            expect(experimentRule().holdout).toEqual({ exclusion_percentage: 10 })
            await waitFor(() => expect(screen.getByLabelText('Holdout excludes')).toHaveValue('10'))
        })
    })

    describe('an object flag', () => {
        const logic = (): ReturnType<typeof featureFlagRulesV2EditorLogic> => featureFlagRulesV2EditorLogic({ id: 11 })
        const json = (label: string): HTMLElement => within(screen.getByLabelText(label)).getByRole('textbox')

        beforeEach(async () => {
            await renderEditor(11)
        })

        it('shows each stored object as formatted JSON', () => {
            expect(json('Value')).toHaveValue('{\n  "columns": 2\n}')
            expect(json('Default value')).toHaveValue('{\n  "columns": 1\n}')
        })

        it('keeps text that is not an object yet as typed and flags it, then stores the object it becomes', () => {
            fireEvent.change(json('Value'), { target: { value: '{"columns": ' } })
            expect(logic().values.draft.config.rules[0]).toMatchObject({ value: '{"columns": ' })
            expect(screen.getByText('Enter a valid JSON object.')).toBeInTheDocument()

            fireEvent.change(json('Value'), { target: { value: '{"columns": 3}' } })
            expect(logic().values.draft.config.rules[0]).toMatchObject({ value: { columns: 3 } })
            expect(json('Value')).toHaveValue('{"columns": 3}')
            expect(screen.queryByText('Enter a valid JSON object.')).not.toBeInTheDocument()
        })

        it('stores a cleared default as null and shows a value set elsewhere', async () => {
            fireEvent.change(json('Default value'), { target: { value: '' } })
            expect(logic().values.draft.config.default_value).toBeNull()

            logic().actions.setConfig({ default_value: { columns: 4 } })
            await waitFor(() => expect(json('Default value')).toHaveValue('{\n  "columns": 4\n}'))
        })
    })

    describe('a number flag', () => {
        const draftConfig = (): Record<string, any> => featureFlagRulesV2EditorLogic({ id: 12 }).values.draft.config

        beforeEach(async () => {
            await renderEditor(12)
        })

        it('stores typed numbers, and an empty input as no number', () => {
            expect(screen.getByLabelText('Value')).toHaveValue(25)
            fireEvent.change(screen.getByLabelText('Value'), { target: { value: '-0.5' } })
            expect(draftConfig().rules[0].value).toBe(-0.5)

            fireEvent.change(screen.getByLabelText('Value'), { target: { value: '' } })
            expect(draftConfig().rules[0].value).toBeNull()
            expect(screen.getByText('Enter a number.')).toBeInTheDocument()

            fireEvent.change(screen.getByLabelText('Default value'), { target: { value: '' } })
            expect(draftConfig().default_value).toBeNull()
        })

        it('empties an input whose number is cleared elsewhere', async () => {
            expect(screen.getByLabelText('Default value')).toHaveValue(10)

            featureFlagRulesV2EditorLogic({ id: 12 }).actions.setConfig({ default_value: null })

            await waitFor(() => expect(screen.getByLabelText('Default value')).toHaveValue(null))
        })

        it('moves focus to the first rule type after deleting the last rule', async () => {
            fireEvent.click(screen.getByLabelText('Rule 1 actions'))
            fireEvent.click(await screen.findByText('Delete rule'))

            await waitFor(() =>
                expect(document.activeElement).toBe(
                    document.querySelector('[data-attr="rules-v2-add-rule-targeted_release"]')
                )
            )
        })
    })
})
