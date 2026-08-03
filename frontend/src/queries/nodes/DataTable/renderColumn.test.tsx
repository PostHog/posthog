import { render } from '@testing-library/react'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import { renderColumn } from './renderColumn'

describe('renderColumn', () => {
    const hogQlQuery: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select email from persons' },
    }

    it('linkifies an email value in a HogQL result column', () => {
        const { container } = render(<>{renderColumn('email', 'nate@mychoicesoftware.com', {}, 0, 1, hogQlQuery)}</>)
        const link = container.querySelector('a')
        expect(link?.getAttribute('href')).toBe('mailto:nate@mychoicesoftware.com')
        expect(link?.textContent).toBe('nate@mychoicesoftware.com')
    })

    it('linkifies a URL value in a HogQL result column', () => {
        const { container } = render(<>{renderColumn('url', 'https://posthog.com', {}, 0, 1, hogQlQuery)}</>)
        const link = container.querySelector('a')
        expect(link?.getAttribute('href')).toBe('https://posthog.com')
    })

    it('does not linkify a plain string value in a HogQL result column', () => {
        const { container } = render(<>{renderColumn('name', 'just some text', {}, 0, 1, hogQlQuery)}</>)
        expect(container.querySelector('a')).toBeNull()
    })
})
