import { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { inlineSourceGrid } from './inlineSourceGrid'

function source(name: string, featured: boolean): SourceConfigResponseApi {
    return { name, label: name, featured } as SourceConfigResponseApi
}

const connectors = [
    source('BigQuery', true),
    source('Hubspot', false),
    source('Stripe', true),
    source('Zendesk', false),
]

describe('inlineSourceGrid', () => {
    it.each([
        { featuredOnly: true, query: '', shown: ['Hubspot', 'BigQuery', 'Stripe'], hiddenCount: 1 },
        { featuredOnly: false, query: '', shown: ['Hubspot', 'BigQuery', 'Stripe', 'Zendesk'], hiddenCount: 0 },
        { featuredOnly: true, query: 's', shown: ['Hubspot', 'Stripe', 'Zendesk'], hiddenCount: 0 },
    ])(
        'leads with detected sources (featuredOnly=$featuredOnly, query=$query)',
        ({ featuredOnly, query, shown, hiddenCount }) => {
            const grid = inlineSourceGrid({ connectors, detectedTypes: new Set(['Hubspot']), featuredOnly, query })

            expect({ shown: grid.shown.map((c) => c.name), hiddenCount: grid.hiddenCount }).toEqual({
                shown,
                hiddenCount,
            })
        }
    )
})
