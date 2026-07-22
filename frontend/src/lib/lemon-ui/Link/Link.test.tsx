import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

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
})
