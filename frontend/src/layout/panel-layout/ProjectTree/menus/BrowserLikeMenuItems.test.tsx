import { fireEvent, render } from '@testing-library/react'

import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'

import { BrowserLikeMenuItems } from './BrowserLikeMenuItems'

describe('BrowserLikeMenuItems', () => {
    // Radix menu items throw outside a menu root, and the guard under test doesn't need one.
    function TestMenuItem({
        onClick,
        'data-attr': dataAttr,
    }: {
        onClick?: (event: React.MouseEvent) => void
        'data-attr'?: string
    }): JSX.Element {
        return <button type="button" data-attr={dataAttr} onClick={onClick} />
    }

    function clickOpenLink(href: string): void {
        const { container } = render(
            <BrowserLikeMenuItems MenuItem={TestMenuItem as unknown as typeof DropdownMenuItem} href={href} />
        )
        fireEvent.click(container.querySelector('[data-attr="tree-item-menu-open-link-button"]')!)
    }

    let openSpy: jest.SpyInstance

    beforeEach(() => {
        openSpy = jest.spyOn(window, 'open').mockImplementation(() => null)
    })

    afterEach(() => {
        openSpy.mockRestore()
    })

    it.each([
        ['javascript:alert(document.cookie)'],
        ['JaVaScRiPt:alert(1)'],
        ['java\tscript:alert(1)'],
        ['  javascript:alert(1)'],
        ['vbscript:msgbox(1)'],
        ['data:text/html,<script>alert(1)</script>'],
        ['//evil.example.com/x'],
        // Browsers read a leading `/\` the same way they read `//`.
        ['/\\evil.example.com/x'],
        ['https://evil.example.com/x'],
    ])('does not open %s', (href) => {
        clickOpenLink(href)

        expect(openSpy).not.toHaveBeenCalled()
    })

    it.each([['/insights/abc123'], ['http://localhost/project/1/insights']])('opens %s', (href) => {
        clickOpenLink(href)

        expect(openSpy).toHaveBeenCalledWith(href, '_blank')
    })
})
