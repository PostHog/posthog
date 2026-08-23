import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { RecordingNotFound } from './RecordingNotFound'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
}))

const mockedUseValues = useValues as jest.Mock

describe('RecordingNotFound', () => {
    afterEach(() => {
        cleanup()
    })

    it('shows the enabled banner when a full team has opted in', () => {
        mockedUseValues.mockReturnValue({
            currentTeam: { id: 1, api_token: 'phc_test', session_recording_opt_in: true },
        })

        render(<RecordingNotFound />)

        expect(screen.getByText('Session replay is enabled for this project')).toBeInTheDocument()
    })

    it('shows the disabled banner when a full team has opted out', () => {
        mockedUseValues.mockReturnValue({
            currentTeam: { id: 1, api_token: 'phc_test', session_recording_opt_in: false },
        })

        render(<RecordingNotFound />)

        expect(screen.getByText('Session replay is disabled for this project')).toBeInTheDocument()
    })

    // A partial team (TeamPublicType) can omit session_recording_opt_in. Reading the absent field
    // as an opt-out is the bug this guards: neither banner may render until the full team loads.
    it('shows no opt-in banner when the team is not fully loaded', () => {
        mockedUseValues.mockReturnValue({
            currentTeam: { id: 1, name: 'Partial team' },
        })

        render(<RecordingNotFound />)

        expect(screen.queryByText('Session replay is enabled for this project')).not.toBeInTheDocument()
        expect(screen.queryByText('Session replay is disabled for this project')).not.toBeInTheDocument()
    })
})
