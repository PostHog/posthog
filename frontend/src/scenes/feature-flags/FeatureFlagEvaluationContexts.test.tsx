import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { FeatureFlagEvaluationContexts } from './FeatureFlagEvaluationContexts'
import { featureFlagLogic } from './featureFlagLogic'

describe('FeatureFlagEvaluationContexts', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/default_evaluation_contexts/': {
                    default_evaluation_contexts: [],
                    available_contexts: [],
                    hidden_contexts: [],
                    enabled: false,
                },
                '/api/environments/:team/default_release_conditions/': { default_groups: [], enabled: false },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        { disabledReason: null, opensEditor: true },
        { disabledReason: "Evaluation contexts can't be changed on this flag yet.", opensEditor: false },
    ])(
        'opens the contexts editor only without a disabled reason: $disabledReason',
        ({ disabledReason, opensEditor }) => {
            const { container } = render(
                <Provider>
                    <BindLogic logic={featureFlagLogic} props={{ id: 'new' }}>
                        <FeatureFlagEvaluationContexts
                            tags={[]}
                            evaluationContexts={[]}
                            flagId={1}
                            context="sidebar"
                            onSave={jest.fn()}
                            evaluationContextsDisabledReason={disabledReason}
                        />
                    </BindLogic>
                </Provider>
            )

            fireEvent.click(container.querySelector('[data-attr="button-edit-evaluation-contexts"]') as Element)

            expect(!!container.querySelector('[data-attr="feature-flag-evaluation-contexts-input"]')).toBe(opensEditor)
        }
    )
})
