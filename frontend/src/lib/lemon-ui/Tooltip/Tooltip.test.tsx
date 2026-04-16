import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { LemonLabel } from '../LemonLabel/LemonLabel'
import { Tooltip } from './Tooltip'

const findOpenTooltipText = (): string | null => {
    const popup = document.querySelector('.Tooltip__popup[data-open]')
    return popup?.textContent ?? null
}

describe('Tooltip', () => {
    afterEach(() => {
        cleanup()
        document.body.innerHTML = ''
    })

    it('shows tooltip when hovering a plain button trigger', async () => {
        const user = userEvent.setup()
        render(
            <Tooltip title="hello tooltip">
                <button data-testid="trigger">trigger</button>
            </Tooltip>
        )
        const trigger = screen.getByRole('button', { name: 'trigger' })
        await act(async () => {
            await user.hover(trigger)
        })
        await waitFor(
            () => {
                expect(findOpenTooltipText()).toContain('hello tooltip')
            },
            { timeout: 2000 }
        )
    })

    it('shows tooltip on LemonLabel info icon', async () => {
        const user = userEvent.setup()
        render(<LemonLabel info="label info tooltip">My Label</LemonLabel>)
        const icon = document.querySelector('.LemonLabel svg.LemonIcon')
        expect(icon).not.toBeNull()
        await act(async () => {
            await user.hover(icon!)
        })
        await waitFor(
            () => {
                expect(findOpenTooltipText()).toContain('label info tooltip')
            },
            { timeout: 2000 }
        )
    })
})
