import { act, cleanup, render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SelfDrivingOnboardingFlow } from './SelfDrivingOnboardingFlow'

// The install step reaches most of the app through its setup options. None of that is navigation,
// and pulling it in costs more than the step order this covers.
jest.mock('./components/SelfDrivingInstallOptions', () => ({ ManualSetupButton: () => null }))
jest.mock('./steps/InstallStep', () => ({ InstallStep: () => null }))
// rough-notation draws through SVG measurement APIs jsdom does not implement.
jest.mock('./RoughMark', () => ({ RoughMark: ({ children }: { children: JSX.Element }) => children }))

describe('SelfDrivingOnboardingFlow', () => {
    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team_id/user_product_list': () => [200, { results: [], count: 0 }],
            },
        })
        initKeaTests()
        router.actions.replace('/onboarding')
    })

    afterEach(() => cleanup())

    it('moves forward into its own history entry, so the browser back button walks the flow', async () => {
        const { getByText } = render(<SelfDrivingOnboardingFlow />)

        await userEvent.click(getByText('Get started'))

        expect(router.values.searchParams['step']).toBe('goals')
        // A replaced entry kept the whole flow in one history entry, so back left onboarding for the
        // history from before sign-up, and the consumed OAuth callback waiting in it.
        expect(router.values.lastMethod).toBe('PUSH')
    })

    it('shows the step the URL names, so going back in history moves the flow', async () => {
        const { queryByText } = render(<SelfDrivingOnboardingFlow />)
        await userEvent.click(queryByText('Get started')!)
        expect(queryByText('What do you want to get done first?')).not.toBeNull()

        act(() => router.actions.push('/onboarding', { step: 'welcome' }))

        expect(queryByText('What do you want to get done first?')).toBeNull()
        expect(queryByText('Get started')).not.toBeNull()
    })

    it('walks history back rather than pushing another entry', async () => {
        const back = jest.spyOn(window.history, 'back').mockImplementation(() => {})
        const { getByText, getByLabelText } = render(<SelfDrivingOnboardingFlow />)
        await userEvent.click(getByText('Get started'))

        await userEvent.click(getByLabelText('Go back'))

        expect(back).toHaveBeenCalled()
        expect(router.values.searchParams['step']).toBe('goals')
        back.mockRestore()
    })
})
