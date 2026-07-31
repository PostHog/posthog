import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import { Link, LinkPrimitive } from './Link'

describe('Link', () => {
    it('opens target="_blank" links via window.open instead of the anchor default action', () => {
        // A link inside a menu that closes (and unmounts the anchor) on click can have its
        // native default action silently dropped by the browser - see LinkPrimitive's onClick.
        const openSpy = jest.spyOn(window, 'open').mockImplementation(() => null)

        render(
            <LinkPrimitive to="/insights/new" target="_blank" disableClientSideRouting>
                open insight
            </LinkPrimitive>
        )

        fireEvent.click(screen.getByText('open insight'))

        expect(openSpy).toHaveBeenCalledWith('/insights/new', '_blank', 'noopener,noreferrer')

        openSpy.mockRestore()
    })

    it('never resolves a javascript: target to an executable href, even with client-side routing disabled', () => {
        // disableClientSideRouting short-circuits the routing rewrite that would otherwise neutralize the
        // scheme, so the scheme block must hold regardless of it (e.g. if the flag is set via prototype pollution).
        render(
            <Link to="javascript:alert(document.domain)" disableClientSideRouting>
                click me
            </Link>
        )

        const anchor = screen.getByText('click me').closest('a')
        expect(anchor?.getAttribute('href') ?? '').not.toMatch(/^javascript:/i)
    })

    it('blocks javascript: targets regardless of casing and whitespace', () => {
        render(
            <Link to="  JavaScript:alert(1)" disableClientSideRouting>
                sneaky
            </Link>
        )

        const anchor = screen.getByText('sneaky').closest('a')
        const href = anchor?.getAttribute('href') ?? ''
        expect(href.replace(/\s/g, '').toLowerCase()).not.toMatch(/^javascript:/)
    })
})
