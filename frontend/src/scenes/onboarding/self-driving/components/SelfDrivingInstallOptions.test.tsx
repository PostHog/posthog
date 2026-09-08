import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { ManualSetupButton } from './SelfDrivingInstallOptions'

// The real list imports SVG logos, which jest maps to an object the grid can't render. Two SDKs
// are enough to exercise the handoff.
jest.mock('scenes/onboarding/legacy/sdks/allSDKs', () => ({
    ALL_SDKS: [
        { name: 'React Native', key: 'react_native', tags: ['Mobile'], image: '/react-native.svg' },
        { name: 'Python', key: 'python', tags: ['Server'], image: '/python.svg' },
    ],
}))

describe('ManualSetupButton', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => cleanup())

    // Regression test for the dead click on the install step: the grid and the instructions used
    // to be two modals, and a pick made while the grid was still closing left the user with
    // neither of them.
    it('swaps the SDK grid for the instructions and back', async () => {
        render(<ManualSetupButton onAdvance={jest.fn()} />)

        fireEvent.click(screen.getByText('Set up manually'))
        expect(await screen.findByText('Manual SDK setup')).toBeInTheDocument()

        fireEvent.click(await screen.findByText('React Native'))
        expect(await screen.findByText('Integrate PostHog with React Native')).toBeInTheDocument()
        expect(screen.queryByText('Manual SDK setup')).not.toBeInTheDocument()

        fireEvent.click(screen.getByText('All SDKs'))
        expect(await screen.findByText('Manual SDK setup')).toBeInTheDocument()
        expect(screen.queryByText('Integrate PostHog with React Native')).not.toBeInTheDocument()
    })
})
