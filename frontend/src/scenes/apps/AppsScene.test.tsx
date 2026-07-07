import '@testing-library/jest-dom'

import { fireEvent, render } from '@testing-library/react'
import { router } from 'kea-router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { AppsScene } from './AppsScene'

describe('AppsScene', () => {
    beforeEach(() => {
        initKeaTests()
    })

    function getSearchInput(container: HTMLElement): HTMLInputElement {
        const input = container.querySelector<HTMLInputElement>('input[data-attr="apps-scene-search"]')
        if (!input) {
            throw new Error('Apps search input not found')
        }
        return input
    }

    // LemonInput's props spread replaces its internal Enter handling (onPressEnter) when a custom
    // onKeyDown is passed, which once silently broke Enter here — this locks the behavior in
    it('opens the selected app on Enter in the search field', () => {
        const { container } = render(<AppsScene />)
        const input = getSearchInput(container)

        fireEvent.change(input, { target: { value: 'annotations' } })
        fireEvent.keyDown(input, { key: 'Enter' })

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.annotations())
    })

    it('moves the selection with arrow keys while the search field keeps focus', () => {
        const { container } = render(<AppsScene />)
        const input = getSearchInput(container)
        input.focus()

        fireEvent.keyDown(input, { key: 'ArrowRight' })
        expect(document.activeElement).toBe(input)

        fireEvent.keyDown(input, { key: 'Enter' })
        const secondItemHref = container
            .querySelectorAll<HTMLAnchorElement>('[data-attr="apps-grid-item"]')[1]
            ?.getAttribute('href')
        expect(secondItemHref).toBeTruthy()
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(
            removeProjectIdIfPresent(secondItemHref ?? '')
        )
    })
})
