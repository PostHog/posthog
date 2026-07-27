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

    it('dismisses when clicking a plain outside element', async () => {
        const { onClickOutside } = renderPopover(<button type="button">outside</button>)

        await userEvent.click(screen.getByText('outside'))

        expect(onClickOutside).toHaveBeenCalled()
    })

    // Regression: a nested menu portaled out of a parent popover's *reference* subtree
    // (e.g. the TaxonomicFilter category pill in the search input suffix) inherits the
    // wrong overlay level, so the parent can't recognize it as nested. The element opts
    // out via CLICK_OUTSIDE_BLOCK_CLASS — clicking it must not dismiss the parent.
    it('does not dismiss when clicking an element marked with CLICK_OUTSIDE_BLOCK_CLASS', async () => {
        const { onClickOutside } = renderPopover(
            <button type="button" className={CLICK_OUTSIDE_BLOCK_CLASS}>
                nested menu item
            </button>
        )

        await userEvent.click(screen.getByText('nested menu item'))

        expect(onClickOutside).not.toHaveBeenCalled()
    })
})
