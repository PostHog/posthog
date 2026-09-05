import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'

import { Popover } from './Popover'

describe('Popover', () => {
    afterEach(() => {
        cleanup()
    })

    function renderPopover(extra?: React.ReactNode): { onClickOutside: jest.Mock } {
        const onClickOutside = jest.fn()
        render(
            <div>
                <Popover visible overlay={<div>overlay content</div>} onClickOutside={onClickOutside}>
                    <button type="button">reference</button>
                </Popover>
                {extra}
            </div>
        )
        return { onClickOutside }
    }

    it.each([
        { target: 'outside', extra: <button type="button">outside</button>, dismisses: true },
        {
            // A nested menu portaled out of a parent popover's *reference* subtree (e.g. the
            // TaxonomicFilter category pill in the search input suffix) inherits the wrong overlay
            // level, so the parent can't recognize it as nested. It opts out via the block class.
            target: 'nested menu item',
            extra: (
                <button type="button" className={CLICK_OUTSIDE_BLOCK_CLASS}>
                    nested menu item
                </button>
            ),
            dismisses: false,
        },
        // The reference is the popover's own trigger. Dismissing on it fights the trigger's toggle
        // handler, which reopens the popover right after — so it never closes.
        { target: 'reference', extra: undefined, dismisses: false },
    ])('clicking $target dismisses: $dismisses', async ({ target, extra, dismisses }) => {
        const { onClickOutside } = renderPopover(extra)

        await userEvent.click(screen.getByText(target))

        expect(onClickOutside).toHaveBeenCalledTimes(dismisses ? 1 : 0)
    })
})
