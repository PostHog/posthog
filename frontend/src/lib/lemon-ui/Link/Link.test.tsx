import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

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

    // Guards the regression where a docs link with no target replaced the app in the current tab.
    const docsTargetCases: [label: string, to: string, target: string | undefined, expected: string | null][] = [
        ['docs link with no target', 'https://posthog.com/docs/libraries/vue-js', undefined, '_blank'],
        ['docs link on www', 'https://www.posthog.com/docs/libraries/vue-js', undefined, '_blank'],
        ['docs link opting out', 'https://posthog.com/docs/libraries/vue-js', '_self', '_self'],
        ['non-docs posthog.com link', 'https://posthog.com/pricing', undefined, null],
        ['in-app link', '/insights/1', undefined, null],
    ]

    it.each(docsTargetCases)('resolves the target of a %s', (label, to, target, expected) => {
        render(
            <Link to={to} target={target}>
                {label}
            </Link>
        )

        expect(screen.getByText(label).closest('a')?.getAttribute('target')).toBe(expected)
    })
})
