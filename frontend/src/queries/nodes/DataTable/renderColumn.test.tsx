import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { NodeKind } from '~/queries/schema/schema-general'
import { DataTableNode } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { renderColumn } from './renderColumn'

describe('renderColumn', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each<[DataTableNode['source']['kind'], string]>([
        [NodeKind.ActorsQuery, 'the Persons scene (regression: used to render as a dead span)'],
        [NodeKind.PersonsNode, 'the legacy persons table'],
    ])('renders property cells as click-to-filter links for %s (%s)', (sourceKind) => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: { kind: sourceKind } as DataTableNode['source'],
            showPropertyFilter: true,
            propertiesViaUrl: true,
        }
        const record = { properties: { plan: 'enterprise' } }

        const result = renderColumn('properties.plan', 'enterprise', record, 0, 1, query, jest.fn())

        render(<>{result}</>)
        expect(screen.getByRole('link')).toBeInTheDocument()
    })
})
