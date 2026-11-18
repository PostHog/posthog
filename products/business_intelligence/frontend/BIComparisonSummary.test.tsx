import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { initKeaTests } from '~/test/init'

import { BIComparisonSummary } from './BIComparisonSummary'
import { DEFAULT_BI_CONFIG } from './biEditorTypes'

describe('comparison member labels', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([false, true])('indexes saved aliases once for the comparison view (card: %s)', (card) => {
        let reads = 0
        const field: BIField = {
            id: 'region',
            name: 'Region',
            expression: 'region',
            type: 'string',
            source: { table: 'example_orders' },
        }
        const aliases = Array.from({ length: 2000 }, (_, index) => ({
            get value(): string {
                reads++
                return `value-${index}`
            },
            label: `Label ${index}`,
        }))
        const config: BIConfig = {
            ...DEFAULT_BI_CONFIG,
            source: field.source,
            rows: [field],
            compareFilter: { compare: true },
            dateRange: { date_from: '-7d' },
            memberAliases: [{ field, aliases }],
        }
        const results = Array.from({ length: 10 }, (_, index) => [`value-${1990 + index}`, index, 'Current period'])
        render(
            <BIComparisonSummary
                config={config}
                columns={['bi_row_region', 'count', 'bi_comparison']}
                results={results}
                card={card}
            />
        )
        expect(screen.getByText(card ? 'Region: Label 1999' : 'Label 1999')).toBeInTheDocument()
        expect(reads).toBeLessThan(aliases.length * 4)
    })
})
