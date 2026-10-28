import type { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { failedDestinationFor } from './destinationFailure'

const PROD: ExternalDataDestinationApi = {
    id: 'prod',
    name: 'Prod',
    type: 'Postgres',
    is_posthog_warehouse: false,
    status: 'failing',
    latest_error: null,
    latest_error_at: null,
    created_at: '2026-08-20T10:00:00Z',
    updated_at: null,
    created_by: null,
    synced_sources: [],
}
const MY_PROD: ExternalDataDestinationApi = { ...PROD, id: 'my-prod', name: 'My Prod' }
const WAREHOUSE: ExternalDataDestinationApi = {
    ...PROD,
    id: 'warehouse',
    name: 'PostHog warehouse',
    type: 'PostHogWarehouse',
    is_posthog_warehouse: true,
}
const REGEX_NAME: ExternalDataDestinationApi = { ...PROD, id: 'regex', name: 'Prod [a+b].* (db)?' }
const BY_ID = Object.fromEntries(
    [PROD, MY_PROD, WAREHOUSE, REGEX_NAME].map((destination) => [destination.id, destination])
)

describe('failedDestinationFor', () => {
    test.each<{
        description: string
        error: string | null | undefined
        candidates: string[]
        expected: ExternalDataDestinationApi | null
    }>([
        { description: 'prefix at the start', error: 'Prod: boom', candidates: [PROD.id], expected: PROD },
        {
            description: 'prefix after a retry message',
            error: 'max retries exceeded: Prod: boom',
            candidates: [PROD.id],
            expected: PROD,
        },
        {
            description: 'a name that contains another name',
            error: 'My Prod: boom',
            candidates: [PROD.id, MY_PROD.id],
            expected: MY_PROD,
        },
        { description: 'a suffix alone', error: 'My Prod: boom', candidates: [PROD.id], expected: null },
        {
            description: 'the longest matching name',
            error: 'Prod: My Prod: boom',
            candidates: [PROD.id, MY_PROD.id],
            expected: MY_PROD,
        },
        {
            description: 'the longest match regardless of order',
            error: 'Prod: My Prod: boom',
            candidates: [MY_PROD.id, PROD.id],
            expected: MY_PROD,
        },
        { description: 'an unknown ID', error: 'Prod: boom', candidates: ['unknown'], expected: null },
        {
            description: 'an unknown ID before a match',
            error: 'Prod: boom',
            candidates: ['unknown', PROD.id],
            expected: PROD,
        },
        {
            description: 'a warehouse row',
            error: 'PostHog warehouse: boom',
            candidates: [WAREHOUSE.id],
            expected: null,
        },
        { description: 'a null error', error: null, candidates: [PROD.id], expected: null },
        { description: 'an undefined error', error: undefined, candidates: [PROD.id], expected: null },
        { description: 'an empty error', error: '', candidates: [PROD.id], expected: null },
        { description: 'no candidates', error: 'Prod: boom', candidates: [], expected: null },
        {
            description: 'a name with regex characters',
            error: `${REGEX_NAME.name}: boom`,
            candidates: [REGEX_NAME.id],
            expected: REGEX_NAME,
        },
        {
            description: 'a name without a separator',
            error: 'max retries exceeded Prod: boom',
            candidates: [PROD.id],
            expected: null,
        },
    ])('matches $description', ({ error, candidates, expected }) => {
        expect(failedDestinationFor(error, candidates, BY_ID)).toBe(expected)
    })
})
