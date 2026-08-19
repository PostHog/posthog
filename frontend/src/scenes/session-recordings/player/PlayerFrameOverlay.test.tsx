import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { SessionPlayerState } from '~/types'

import { PlayerFrameOverlay } from './PlayerFrameOverlay'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock

describe('PlayerFrameOverlay', () => {
    afterEach(() => {
        cleanup()
    })

    const renderWithState = (overrides: Record<string, unknown>): void => {
        mockedUseActions.mockReturnValue({
            setPlay: jest.fn(),
            retryLoadingSnapshots: jest.fn(),
            togglePlayPause: jest.fn(),
            setQuickEmojiIsOpen: jest.fn(),
        })
        mockedUseValues.mockReturnValue({
            currentPlayerState: SessionPlayerState.ERROR,
            endReached: false,
            logicProps: {},
            isWaitingForIngestion: false,
            seekIndicator: null,
            quickEmojiIsOpen: false,
            ...overrides,
        })
        render(<PlayerFrameOverlay />)
    }

    it('shows a retryable terminal card for a stuck buffer instead of an endless spinner', () => {
        renderWithState({ playerError: 'bufferTimeout' })

        expect(screen.getByText(/did not finish loading/i)).toBeInTheDocument()
        expect(screen.getByText('Retry')).toBeInTheDocument()
    })
})
