import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from './OnboardingStep'

jest.mock('./OnboardingBreadcrumbs', () => ({ OnboardingBreadcrumbs: () => null }))

describe('OnboardingStep', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // A gated Continue keeps its solid primary styling and only explains itself in a tooltip, so the
    // step itself has to say why the button does nothing.
    test.each([
        ['the reason', undefined, 'Installation is not complete'],
        ['the hint when one is given', 'Run the install command above.', 'Run the install command above.'],
    ])('states %s next to the buttons', (_name, continueDisabledHint, expected) => {
        render(
            <Provider>
                <OnboardingStep
                    stepKey={OnboardingStepKey.INSTALL}
                    title="Install"
                    continueDisabledReason="Installation is not complete"
                    continueDisabledHint={continueDisabledHint}
                >
                    <div />
                </OnboardingStep>
            </Provider>
        )

        expect(screen.getByTestId('onboarding-continue-blocked')).toHaveTextContent(expected)
    })

    it('says nothing when Continue is open', () => {
        render(
            <Provider>
                <OnboardingStep stepKey={OnboardingStepKey.INSTALL} title="Install">
                    <div />
                </OnboardingStep>
            </Provider>
        )

        expect(screen.queryByTestId('onboarding-continue-blocked')).toBeNull()
    })
})
