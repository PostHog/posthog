import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { SELF_DRIVING_ONBOARDING_EVENT_PROPS } from '../../onboardingEventUsageLogic'
import { productKeysForSetup, resolveSetup } from '../../shared/useCases'
import { useCaseSelectionLogic } from '../useCaseSelectionLogic'
import { UseCasesStep } from './UseCasesStep'

describe('UseCasesStep', () => {
    let logic: ReturnType<typeof useCaseSelectionLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests(false)
        logic = useCaseSelectionLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    it('clears the previous use case before continuing without one', () => {
        logic.actions.selectUseCase('find_problems')
        const onSkip = jest.fn()

        render(<UseCasesStep onContinue={jest.fn()} onSkip={onSkip} />)
        fireEvent.click(screen.getByText('Continue without choosing a goal'))

        expect(logic.values.selectedUseCase).toBeNull()
        expect(onSkip).toHaveBeenCalledTimes(1)
    })

    it('reports the selected use case with the self-driving event schema', () => {
        const capture = jest.spyOn(posthog, 'capture')

        logic.actions.selectUseCase('find_problems')

        expect(capture.mock.calls).toContainEqual([
            'onboarding use case selected',
            {
                use_case: 'find_problems',
                recommended_products: productKeysForSetup(resolveSetup('find_problems')),
                ...SELF_DRIVING_ONBOARDING_EVENT_PROPS,
            },
        ])

        capture.mockRestore()
    })
})
