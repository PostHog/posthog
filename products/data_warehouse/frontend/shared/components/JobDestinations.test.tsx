import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { JobDestinations } from './JobDestinations'

const WAREHOUSE = {
    id: '01a03e9c-1b76-0000-9079-2a0ee2186dea',
    type: 'PostHogWarehouse',
    name: 'PostHog warehouse',
    config: {},
    integration: null,
    is_posthog_warehouse: true,
} as ExternalDataDestinationApi

const POSTGRES = {
    id: '01a03e9c-1b7c-0000-71ce-5e5d7b04df8f',
    type: 'Postgres',
    name: 'Customer Postgres',
    config: { database: 'analytics', schema: 'customer_sync' },
    integration: 1,
    is_posthog_warehouse: false,
} as ExternalDataDestinationApi

const BY_ID = { [WAREHOUSE.id]: WAREHOUSE, [POSTGRES.id]: POSTGRES }

describe('JobDestinations', () => {
    afterEach(cleanup)

    // The backend snapshots no ids for a run that wrote to the warehouse alone, which is every
    // run on a source nobody has pointed elsewhere. Showing a dash there reads as "went nowhere".
    it.each<[string, Record<string, ExternalDataDestinationApi>]>([
        ['the project has a warehouse row', BY_ID],
        ['the project has never configured a destination', {}],
    ])('shows the warehouse for a run that recorded no destinations when %s', (_, destinationsById) => {
        render(<JobDestinations destinationIds={[]} destinationsById={destinationsById} />)

        expect(screen.getByAltText('PostHog warehouse')).toBeInTheDocument()
        expect(screen.queryByText('—')).not.toBeInTheDocument()
    })

    it('shows a logo for each destination a run recorded', () => {
        render(<JobDestinations destinationIds={[WAREHOUSE.id, POSTGRES.id]} destinationsById={BY_ID} />)

        expect(screen.getByAltText('PostHog warehouse')).toBeInTheDocument()
        expect(screen.getByAltText('Postgres')).toBeInTheDocument()
    })

    it('stays quiet while the destination lookup is still loading', () => {
        render(<JobDestinations destinationIds={[POSTGRES.id]} destinationsById={{}} loading />)

        expect(screen.getByText('—')).toBeInTheDocument()
    })

    it('says how many destinations a run used once they have been deleted', () => {
        render(<JobDestinations destinationIds={['01a03e9c-0000-0000-0000-000000000000']} destinationsById={BY_ID} />)

        expect(screen.getByText('1 removed')).toBeInTheDocument()
    })
})
