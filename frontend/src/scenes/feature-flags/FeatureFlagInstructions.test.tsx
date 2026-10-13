import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagConfig, SDKKey } from '~/types'

import { OPTIONS } from './FeatureFlagCodeOptions'
import { CodeInstructions } from './FeatureFlagInstructions'
import { NEW_FLAG } from './featureFlagLogic'

describe('CodeInstructions', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team/groups_types/': [] } })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each<{ format: string; filters: FeatureFlagConfig; disabled: boolean }>([
        {
            format: 'v1',
            filters: { groups: [{ properties: [], rollout_percentage: 100, variant: null }] },
            disabled: false,
        },
        {
            format: 'rules v2',
            filters: { version: 2, return_type: 'boolean', default_value: false, rules: [] },
            disabled: true,
        },
    ])('a $format flag has the local evaluation option disabled: $disabled', ({ filters, disabled }) => {
        const { container } = render(
            <Provider>
                <CodeInstructions
                    options={OPTIONS}
                    featureFlag={{ ...NEW_FLAG, id: 1, key: 'checkout', filters }}
                    selectedLanguage={SDKKey.NODE_JS}
                />
            </Provider>
        )

        const checkbox = container.querySelector('[data-attr="flags-code-example-local-eval-option"] input')
        expect((checkbox as HTMLInputElement).disabled).toBe(disabled)
    })
})
