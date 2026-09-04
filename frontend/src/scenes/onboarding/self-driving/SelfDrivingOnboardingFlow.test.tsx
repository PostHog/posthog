import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { SelfDrivingOnboardingFlow } from './SelfDrivingOnboardingFlow'

describe('SelfDrivingOnboardingFlow', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests(false)
        router.actions.replace(urls.onboarding(), { step: 'goals' })
    })

    afterEach(() => {
        cleanup()
    })

    it('labels the back control instead of showing a bare arrow', () => {
        render(<SelfDrivingOnboardingFlow />)

        expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument()
    })

    it('lets the progress dots undo a back press and return to the step reached', () => {
        render(<SelfDrivingOnboardingFlow />)

        fireEvent.click(screen.getByRole('button', { name: 'Back' }))
        expect(router.values.searchParams['step']).toBe('welcome')

        fireEvent.click(screen.getByRole('button', { name: 'Go to Your goal' }))
        expect(router.values.searchParams['step']).toBe('goals')
    })

    it('keeps steps the user has not reached out of the dots', () => {
        render(<SelfDrivingOnboardingFlow />)

        expect(screen.queryByRole('button', { name: 'Go to Install PostHog' })).not.toBeInTheDocument()
    })
})
