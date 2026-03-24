import '@testing-library/jest-dom'

import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { PostOnboardingModal } from './PostOnboardingModal'
import { postOnboardingModalLogic } from './postOnboardingModalLogic'

const mockTrigger = jest.fn()

jest.mock('lib/components/Hogfetti/Hogfetti', () => ({
    useHogfetti: () => ({
        trigger: mockTrigger,
        HogfettiComponent: () => <div data-attr="hogfetti" />,
    }),
}))

jest.mock('lib/components/hedgehogs', () => ({
    SupermanHog: (props: any) => <div data-attr="superman-hog" {...props} />,
}))

jest.mock('~/layout/navigation-3000/components/KeyboardShortcut', () => ({
    KeyboardShortcut: (props: any) => <kbd data-attr="keyboard-shortcut" {...props} />,
}))

// Suppress posthog.capture calls from the logic listeners
jest.mock('posthog-js', () => ({
    ...jest.requireActual('posthog-js'),
    capture: jest.fn(),
    init: jest.fn(),
    opt_out_capturing: jest.fn(),
}))

describe('PostOnboardingModal', () => {
    let logic: ReturnType<typeof postOnboardingModalLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = postOnboardingModalLogic()
        logic.mount()
        mockTrigger.mockClear()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('does not render when isModalOpen is false', () => {
        render(<PostOnboardingModal />)
        expect(screen.queryByText("You're all set!")).not.toBeInTheDocument()
    })

    it('renders modal when isModalOpen is true', () => {
        logic.actions.openPostOnboardingModal()
        render(<PostOnboardingModal />)
        // getAllByText handles the case where react-modal may duplicate content in the DOM
        expect(screen.getAllByText("You're all set!").length).toBeGreaterThan(0)
    })

    it('displays congratulations description text', () => {
        logic.actions.openPostOnboardingModal()
        render(<PostOnboardingModal />)
        expect(screen.getAllByText(/Congratulations on setting up PostHog/).length).toBeGreaterThan(0)
    })

    it('displays SupermanHog illustration', () => {
        logic.actions.openPostOnboardingModal()
        render(<PostOnboardingModal />)
        expect(screen.getAllByTestId('superman-hog').length).toBeGreaterThan(0)
    })

    it('displays three keyboard shortcuts', () => {
        logic.actions.openPostOnboardingModal()
        render(<PostOnboardingModal />)
        expect(screen.getAllByText('Search anything').length).toBeGreaterThan(0)
        expect(screen.getAllByText('Open Quick Start').length).toBeGreaterThan(0)
        expect(screen.getAllByText('View all shortcuts').length).toBeGreaterThan(0)
    })

    it('triggers hogfetti when modal opens', async () => {
        jest.useFakeTimers()
        logic.actions.openPostOnboardingModal()
        render(<PostOnboardingModal />)

        // Flush the initial trigger (0ms) and advance through the 400ms + 400ms delays
        // Each act flushes promises so the async chain can progress
        await act(async () => {
            jest.advanceTimersByTime(400)
        })
        await act(async () => {
            jest.advanceTimersByTime(400)
        })
        await act(async () => {
            jest.advanceTimersByTime(200)
        })

        expect(mockTrigger).toHaveBeenCalledTimes(3)
        jest.useRealTimers()
    })

    it('CTA button click closes the modal', async () => {
        logic.actions.openPostOnboardingModal()
        render(<PostOnboardingModal />)

        const ctaButtons = screen.getAllByText('Start Quick Start')
        await userEvent.click(ctaButtons[0])

        expect(logic.values.isModalOpen).toBe(false)
    })
})
