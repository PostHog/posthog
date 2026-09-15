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

    // Regression: a nested menu portaled out of a parent popover's *reference* subtree (e.g. the
    // TaxonomicFilter category pill in the search input suffix) inherits the wrong overlay level, so
    // the parent can't recognize it as nested. It opts out with CLICK_OUTSIDE_BLOCK_CLASS instead.
    it('does not dismiss when clicking an element opted out with the block class', async () => {
        const { onClickOutside } = renderPopover(
            <button type="button" className={CLICK_OUTSIDE_BLOCK_CLASS}>
                nested menu item
            </button>
        )

        await userEvent.click(screen.getByText('nested menu item'))

        expect(onClickOutside).not.toHaveBeenCalled()
    })

    // Regression: posthog-js renders a survey into a shadow host appended to <body>, and floating-ui
    // resolves the press target to the element inside that shadow tree. Answering a survey closed the
    // taxonomic filter underneath it and discarded the search the person had typed. Built imperatively
    // because a shadow tree can't be expressed as JSX children.
    it('does not dismiss when clicking a survey posthog-js rendered', async () => {
        const { onClickOutside } = renderPopover()
        const host = document.createElement('div')
        host.className = 'PostHogSurvey-0000abcd'
        const rating = document.createElement('button')
        host.attachShadow({ mode: 'open' }).appendChild(rating)
        document.body.appendChild(host)

        await userEvent.click(rating)

        expect(onClickOutside).not.toHaveBeenCalled()
        host.remove()
    })
})
