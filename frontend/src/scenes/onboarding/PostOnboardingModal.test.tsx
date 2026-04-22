import '@testing-library/jest-dom'

import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ProductKey } from '~/queries/schema/schema-general'
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
    SupermanHog: (props: any) => <div data-testid="superman-hog" {...props} />,
}))

jest.mock('~/layout/navigation-3000/components/KeyboardShortcut', () => ({
    KeyboardShortcut: (props: any) => <kbd data-attr="keyboard-shortcut" {...props} />,
}))

jest.mock('posthog-js', () => ({
    ...jest.requireActual('posthog-js'),
    capture: jest.fn(),
    init: jest.fn(),
    opt_out_capturing: jest.fn(),
}))

describe('PostOnboardingModal', () => {
    let logic: ReturnType<typeof postOnboardingModalLogic.build>

    beforeEach(() => {
        jest.useFakeTimers()
        localStorage.clear()
        initKeaTests()
        logic = postOnboardingModalLogic()
        logic.mount()
        mockTrigger.mockClear()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    async function openAndWaitForReady(): Promise<void> {
        logic.actions.openPostOnboardingModal(ProductKey.PRODUCT_ANALYTICS)
        render(<PostOnboardingModal />)
        // The component waits 500ms before setting ready=true
        await act(async () => {
            jest.advanceTimersByTime(500)
        })
    }

    it('does not render when isModalOpen is false', () => {
        render(<PostOnboardingModal />)
        expect(screen.queryByText("You're ready to go")).not.toBeInTheDocument()
    })

    it('renders modal when opened and ready', async () => {
        await openAndWaitForReady()
        expect(screen.getAllByText("You're ready to go").length).toBeGreaterThan(0)
    })

    it('triggers hogfetti when modal opens', async () => {
        await openAndWaitForReady()

        // Advance through the 400ms + 400ms delays between triggers
        await act(async () => {
            jest.advanceTimersByTime(400)
        })
        await act(async () => {
            jest.advanceTimersByTime(400)
        })

        expect(mockTrigger).toHaveBeenCalledTimes(3)
    })

    it('CTA button click closes the modal', async () => {
        await openAndWaitForReady()

        const ctaButtons = screen.getAllByText("Let's get started")
        await act(async () => {
            await userEvent.setup({ advanceTimers: jest.advanceTimersByTime }).click(ctaButtons[0])
        })

        expect(logic.values.isModalOpen).toBe(false)
    })
})
