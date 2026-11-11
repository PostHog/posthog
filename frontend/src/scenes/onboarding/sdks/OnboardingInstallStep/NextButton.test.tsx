import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

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

    it('skipping installation advances to the next step', () => {
        render(<NextButton installationComplete={false} />)

        fireEvent.click(screen.getByText('Skip installation'))

        expect(logic.values.stepId).toBe('configure:product_analytics')
    })
})
