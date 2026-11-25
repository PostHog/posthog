import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
            open: async () => {
                await userEvent.tab()
                await userEvent.keyboard(key)
            },
        })),
    ])('opens by $method as a named dialog without reaching its parent, then Escape closes it', async ({ open }) => {
        const parentHandler = jest.fn()
        render(
            // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions -- stands in for a sortable header or clickable card
            <div onClick={parentHandler} onKeyDown={parentHandler}>
                <Infotip label="About average position">1 means your site is the first source cited.</Infotip>
            </div>
        )
        const trigger = screen.getByLabelText('About average position')

        await open(trigger)

        const popup = await screen.findByRole('dialog')
        expect(popup.getAttribute('aria-label')).toBe('About average position')
        expect(trigger.getAttribute('aria-expanded')).toBe('true')
        expect(popup.getAttribute('aria-describedby')).toBe(
            screen.getByText('1 means your site is the first source cited.').id
        )
        await userEvent.click(screen.getByText('1 means your site is the first source cited.'))

        await userEvent.keyboard('{Escape}')

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
        expect(document.activeElement).toBe(trigger)
        expect(parentHandler).not.toHaveBeenCalled()
    })

    it('opens instead of following a link it sits in', async () => {
        render(
            // eslint-disable-next-line react/forbid-elements -- stands in for a router link around a title
            <a href="/persons/1">
                Person <Infotip label="About person">Explains the person.</Infotip>
            </a>
        )

        const followed = fireEvent.click(screen.getByLabelText('About person'))

        expect(followed).toBe(false)
        expect(await screen.findByRole('dialog')).toBeTruthy()
    })

    it('lets a keyboard user reach a link inside the popup', async () => {
        render(
            <Infotip label="About mentioned">
                The answer names your brand.{' '}
                {/* eslint-disable-next-line react/forbid-elements -- quill has no app router, so a plain link stands in */}
                <a href="https://posthog.com/docs">Read the docs</a>
            </Infotip>
        )

        await userEvent.tab()
        await userEvent.keyboard('{Enter}')

        await waitFor(() => expect(document.activeElement).toBe(screen.getByText('Read the docs')))
    })
})
