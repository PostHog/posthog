import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'

import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagRulesV2Editor } from './FeatureFlagRulesV2Editor'

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

describe('FeatureFlagRulesV2Editor', () => {
    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/feature_flags/7/': V2_FLAG,
                '/api/projects/:team/feature_flags/7/status': { status: 'active', reason: 'mock reason' },
            },
        })
        initKeaTests()
        const pageLogic = featureFlagLogic({ id: 7 })
        pageLogic.mount()
        await expectLogic(pageLogic).toDispatchActions(['loadFeatureFlagSuccess']).toFinishAllListeners()
        render(
            <Provider>
                <FeatureFlagRulesV2Editor id={7} />
            </Provider>
        )
    })

    afterEach(cleanup)

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
