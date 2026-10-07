import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { FeatureFlagRulesV2DraftExperimentRule } from '~/types'

import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagRulesV2Editor } from './FeatureFlagRulesV2Editor'
import { featureFlagRulesV2EditorLogic } from './featureFlagRulesV2EditorLogic'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
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

const STRING_SPLIT_FLAG = {
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
                experiment_id: null,
                paused: false,
                rollout_percentage: 50,
                on_rollout_miss: 'continue',
                assignment_algorithm: 'sha1_60_v1',
                seed: 'split-seed',
                variants: [
                    { key: 'control', weight: 50, value: 'standard' },
                    { key: 'compact', weight: 50, value: 'compact' },
                ],
                holdout: { id: null, seed: 'holdout-seed', exclusion_percentage: 5 },
            },
        ],
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
                '/api/projects/:team/feature_flags/9/': STRING_SPLIT_FLAG,
                '/api/projects/:team/feature_flags/:id/status': { status: 'active', reason: 'mock reason' },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    describe('a boolean flag', () => {
        beforeEach(async () => {
            await renderEditor(7)
        })

        it('names each text input by its label', () => {
            expect(screen.getByLabelText('Flag key')).toHaveValue('new-checkout')
            expect(screen.getAllByLabelText(/^Description/).map((input) => input.tagName)).toEqual([
                'TEXTAREA',
                'INPUT',
                'INPUT',
            ])
            expect(screen.getByLabelText('Rollout percentage')).toHaveValue('20')
        })

        // Moving the card re-inserts it, which drops focus. React's commit then refocuses the button,
        // because it is still mounted.
        it('keeps focus on the rule a keyboard user moved down', async () => {
            const [moveDown] = document.querySelectorAll<HTMLElement>('[data-attr="rules-v2-move-rule-down"]')
            moveDown.focus()
            fireEvent.click(moveDown)

            await waitFor(() =>
                expect(document.querySelector('[data-attr="rules-v2-rule"] input')).toHaveValue('Everyone else')
            )
            const focusedRule = document.activeElement?.closest('[data-attr="rules-v2-rule"]')
            expect(focusedRule).toHaveTextContent('Rule 2')
            expect(focusedRule?.querySelector('input')).toHaveValue('Beta users')
        })
    })

    describe('a variant split', () => {
        const split = (): FeatureFlagRulesV2DraftExperimentRule =>
            featureFlagRulesV2EditorLogic({ id: 9 }).values.draft.config
                .rules[0] as FeatureFlagRulesV2DraftExperimentRule
        const click = (dataAttr: string, index = 0): void => {
            fireEvent.click(document.querySelectorAll<HTMLElement>(`[data-attr="${dataAttr}"]`)[index])
        }

        beforeEach(async () => {
            await renderEditor(9)
        })

        it('labels every variant input and shows no seed', () => {
            expect(screen.getByLabelText('Variant 1 key')).toHaveValue('control')
            expect(screen.getByLabelText('Variant 2 value')).toHaveValue('compact')
            expect(screen.getByLabelText('Variant 2 weight')).toHaveValue('50')
            expect(screen.getByLabelText('Held out')).toHaveValue('5')
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

            expect(split().variants).toEqual([
                { key: 'spacious', weight: 33.33, value: 'spacious' },
                { key: 'compact', weight: 33.33, value: 'compact' },
            ])
            expect(split()).toMatchObject({ seed: 'split-seed', holdout: { seed: 'holdout-seed' } })
        })

        it('pauses the split and removes its holdout', () => {
            click('rules-v2-split-paused')
            click('rules-v2-split-holdout')

            expect(split()).toMatchObject({ paused: true })
            expect(split()).not.toHaveProperty('holdout')
            expect(screen.queryByLabelText('Held out')).not.toBeInTheDocument()
        })
    })
})
