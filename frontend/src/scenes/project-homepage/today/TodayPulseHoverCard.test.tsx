import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayPulseHoverCard } from './TodayPulseHoverCard'

describe('TodayPulseHoverCard', () => {
    afterEach(() => cleanup())

    it.each([true, false])('stays closed after Escape restores focus (focusable=%s)', async (focusable) => {
        const user = userEvent.setup()
        render(
            <>
                <TodayPulseHoverCard focusable={focusable} card={<button>Pin number</button>} onOpenChange={() => {}}>
                    {focusable ? 'Preview number' : <LinkPrimitive to="#insight">Open insight</LinkPrimitive>}
                </TodayPulseHoverCard>
                <button>Outside</button>
            </>
        )

        await user.hover(screen.getByText(focusable ? 'Preview number' : 'Open insight'))
        expect(await screen.findByText('Pin number')).toBeVisible()
        await user.keyboard('{Escape}')
        await waitFor(() => expect(screen.getByText(focusable ? 'Preview number' : 'Open insight')).toHaveFocus())
        await waitFor(() => expect(screen.queryByText('Pin number')).not.toBeInTheDocument())

        await user.click(screen.getByText('Outside'))
        await user.tab({ shift: true })
        expect(await screen.findByText('Pin number')).toBeVisible()
    })
})
