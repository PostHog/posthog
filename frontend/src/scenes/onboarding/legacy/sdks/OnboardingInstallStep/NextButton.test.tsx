import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { onboardingLogic } from '../../onboardingLogic'
import { NextButton } from './NextButton'

describe('NextButton', () => {
    let logic: ReturnType<typeof onboardingLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = onboardingLogic()
        logic.mount()
        logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
        logic.actions.setStepId('install:product_analytics')
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    it('falls back to the legacy step machine when no override is supplied', () => {
        render(<NextButton installationComplete={false} />)

        fireEvent.click(screen.getByText('Skip installation'))

        expect(logic.values.stepId).toBe('configure:product_analytics')
    })

    it('calls the supplied override instead of the legacy step machine (self-driving)', () => {
        // Regression test for the self-driving "Skip installation" dead click: the modal
        // that hosts this button reuses the legacy NextButton, which used to always dispatch
        // into the legacy onboardingLogic step machine that self-driving never reads.
        const onAdvance = jest.fn()
        const capture = jest.spyOn(posthog, 'capture')

        render(<NextButton installationComplete={false} onAdvance={onAdvance} />)

        fireEvent.click(screen.getByText('Skip installation'))

        expect(onAdvance).toHaveBeenCalledTimes(1)
        // The legacy machine must stay untouched when an override is supplied.
        expect(logic.values.stepId).toBe('install:product_analytics')
        expect(capture.mock.calls.map((call) => call[0])).toContain('onboarding step skipped')

        capture.mockRestore()
    })
})
