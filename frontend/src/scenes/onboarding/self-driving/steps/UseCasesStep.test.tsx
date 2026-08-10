import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

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

    it('clears the previous goal before continuing without one', () => {
        logic.actions.selectUseCase('find_problems')
        const onSkip = jest.fn()

        render(<UseCasesStep onContinue={jest.fn()} onSkip={onSkip} />)
        fireEvent.click(screen.getByText('Continue without choosing a goal'))

        expect(logic.values.selectedUseCase).toBeNull()
        expect(onSkip).toHaveBeenCalledTimes(1)
    })
})
