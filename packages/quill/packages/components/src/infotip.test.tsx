import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { Infotip } from './infotip'

describe('Infotip', () => {
    afterEach(cleanup)

    it.each([
        { method: 'click', open: (trigger: HTMLElement) => userEvent.click(trigger) },
        {
            method: 'touch',
            open: (trigger: HTMLElement) => userEvent.pointer({ keys: '[TouchA]', target: trigger }),
        },
        ...['{Enter}', ' '].map((key) => ({
            method: `Tab then ${key === ' ' ? 'Space' : 'Enter'}`,
            open: async (trigger: HTMLElement) => {
                await userEvent.tab()
                expect(document.activeElement).toBe(trigger)
                await userEvent.keyboard(key)
            },
        })),
    ])('opens by $method as a named dialog, then Escape closes it and returns focus', async ({ open }) => {
        render(<Infotip label="About average position">1 means your site is the first source cited.</Infotip>)
        const trigger = screen.getByLabelText('About average position')

        await open(trigger)

        const popup = await screen.findByRole('dialog')
        expect(popup.getAttribute('aria-label')).toBe('About average position')
        expect(trigger.getAttribute('aria-expanded')).toBe('true')
        expect(popup.getAttribute('aria-describedby')).toBe(
            screen.getByText('1 means your site is the first source cited.').id
        )

        await userEvent.keyboard('{Escape}')

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
        expect(document.activeElement).toBe(trigger)
    })

    it('lets a keyboard user reach a link inside the popup', async () => {
        render(
            <Infotip label="About mentioned">
                The answer names your brand. <a href="https://posthog.com/docs">Read the docs</a>
            </Infotip>
        )

        await userEvent.tab()
        await userEvent.keyboard('{Enter}')

        await waitFor(() => expect(document.activeElement).toBe(screen.getByText('Read the docs')))
    })

    it('stays open when clicked well after hover opened it, and the next click closes it', async () => {
        jest.useFakeTimers()
        try {
            const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })
            render(<Infotip label="About mentioned">The answer names your brand.</Infotip>)
            const trigger = screen.getByLabelText('About mentioned')

            await user.hover(trigger)
            act(() => jest.advanceTimersByTime(1000))
            expect(trigger.getAttribute('aria-expanded')).toBe('true')

            await user.click(trigger)
            await user.unhover(trigger)
            act(() => jest.advanceTimersByTime(1000))
            expect(trigger.getAttribute('aria-expanded')).toBe('true')

            await user.click(trigger)
            act(() => jest.advanceTimersByTime(1000))
            expect(trigger.getAttribute('aria-expanded')).toBe('false')
        } finally {
            jest.useRealTimers()
        }
    })
})
