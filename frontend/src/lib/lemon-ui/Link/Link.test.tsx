import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { Link } from './Link'

describe('Link', () => {
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

    const schemeCases: [scheme: string, target: string][] = [
        ['chrome-extension', 'chrome-extension://abcdefghijklmnop/index.html'],
        ['capacitor', 'capacitor://localhost/home'],
        ['https', 'https://example.com/page'],
    ]

    it.each(schemeCases)('keeps a %s: target out of the app routes', (scheme, target) => {
        // The href alone is not enough: `router.actions.push` rejects a cross-origin URL with a
        // `SecurityError`, so the click must reach the browser instead of the router.
        const unmountRouter = router.mount()
        const push = jest.spyOn(router.actions, 'push').mockImplementation(() => {})
        const text = `launch ${scheme}`
        render(<Link to={target}>{text}</Link>)

        const anchor = screen.getByText(text).closest('a')
        expect(anchor).toHaveAttribute('href', target)

        fireEvent.click(anchor!)
        expect(push).not.toHaveBeenCalled()

        push.mockRestore()
        unmountRouter()
    })

    // The command palette depends on modifier clicks NOT reaching the passed onClick, so it
    // handles them in the capture phase instead. If this ever starts forwarding them, that
    // palette handler and this onClick would both run, opening a new tab and navigating in place.
    const modifierCases: [label: string, init: MouseEventInit, expectedCalls: number][] = [
        ['plain', {}, 1],
        ['meta', { metaKey: true }, 0],
        ['ctrl', { ctrlKey: true }, 0],
    ]

    it.each(modifierCases)('invokes the passed onClick for a %s click %s time(s)', (label, init, expectedCalls) => {
        const onClick = jest.fn()
        const text = `modifier target ${label}`
        render(
            <Link to="/insights/1" disableClientSideRouting onClick={onClick}>
                {text}
            </Link>
        )

        fireEvent.click(screen.getByText(text), init)
        expect(onClick).toHaveBeenCalledTimes(expectedCalls)
    })
})
