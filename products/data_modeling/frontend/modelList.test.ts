import { DataWarehouseSavedQueryOrigin } from '~/queries/schema/schema-general'
import { DataWarehouseSavedQuery } from '~/types'

import type { EndpointResponseApi } from 'products/endpoints/frontend/generated/api.schemas'

import { groupEndpointVersions } from './modelList'

describe('groupEndpointVersions', () => {
    it('keeps an unsupported current version visible alongside its backed history', () => {
        const earlier = {
            id: 'saved-query',
            name: 'internal_name_v1',
            origin: DataWarehouseSavedQueryOrigin.ENDPOINT,
            endpoint: { name: 'weekly', version: 1, is_current: false },
            is_materialized: true,
        } as DataWarehouseSavedQuery
        const endpoint = {
            id: 'published',
            name: 'weekly',
            current_version: 2,
            versions_count: 2,
            is_materialized: false,
            model_unavailable_reason: 'This query cannot be compiled.',
        } as EndpointResponseApi

        const [row] = groupEndpointVersions([earlier], [endpoint])

        expect(row.endpoint).toEqual({ name: 'weekly', version: 2, is_current: true })
        expect(row.modelUnavailableReason).toBe(endpoint.model_unavailable_reason)
        expect(row.endpointVersions?.map((version) => version.endpoint?.version)).toEqual([2, 1])
    })

    it.each([1, 2])(
        'groups versions by endpoint identity and displays current v%s, even after a rollback',
        (current) => {
            const view = { id: 'view', name: 'weekly_v1' } as DataWarehouseSavedQuery
            const versions = [1, 2].map(
                (version) =>
                    ({
                        id: `version-${version}`,
                        name: `internal_name_${version}`,
                        origin: DataWarehouseSavedQueryOrigin.ENDPOINT,
                        endpoint: { name: 'weekly', version, is_current: version === current },
                        is_materialized: version === 1,
                    }) as DataWarehouseSavedQuery
            )

            const rows = groupEndpointVersions([view, ...versions])

            expect(rows).toHaveLength(2)
            expect(rows[0]).toEqual(view)
            expect(rows[1].id).toBe(`version-${current}`)
            expect(rows[1].endpointVersions?.map((version) => version.endpoint?.version)).toEqual([2, 1])
            expect(versions.map((version) => version.endpoint?.version)).toEqual([1, 2])
        }
    )
})
