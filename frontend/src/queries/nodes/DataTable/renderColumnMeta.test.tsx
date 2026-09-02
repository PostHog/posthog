import { render } from '@testing-library/react'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

import { renderColumnMeta } from './renderColumnMeta'

const personsTable = setLatestVersionsOnQuery({
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.ActorsQuery, select: [] },
}) as DataTableNode

function headerText(key: string): string {
    const { title } = renderColumnMeta(key, personsTable)
    return render(<>{title}</>).container.textContent ?? ''
}

describe('renderColumnMeta', () => {
    it.each([
        ["properties.plan_tier ? 'paid' : 'free' -- Plan", 'Plan'],
        ["properties.$browser IN ('Chrome', 'Firefox') ? 'yes' : 'no' -- Major browser", 'Major browser'],
        ['person.properties.signup_source -- Acquisition', 'Acquisition'],
        ["concat(properties.first_name, ' ', properties.last_name) -- Full name", 'Full name'],
        ['person_display_name -- Person', 'Person'],
    ])('shows the trailing comment as the header for %s', (key: string, expected: string): void => {
        expect(headerText(key)).toBe(expected)
    })

    it.each([
        ['properties.plan_tier', 'plan_tier'],
        ['person.properties.signup_source', 'signup_source'],
    ])('shows the property name for %s', (key: string, expected: string): void => {
        expect(headerText(key)).toBe(expected)
    })
})
