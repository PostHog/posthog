import { DataWarehouseSavedQueryOrigin } from '~/queries/schema/schema-general'
import { DataWarehouseSavedQuery } from '~/types'

import type { EndpointResponseApi, EndpointVersionResponseApi } from 'products/endpoints/frontend/generated/api.schemas'

export type ModelListRow = DataWarehouseSavedQuery & {
    endpointVersions?: ModelListRow[]
    endpointVersionCount?: number
    modelUnavailableReason?: string | null
    isEndpointPlaceholder?: boolean
}

export function groupEndpointVersions(
    views: DataWarehouseSavedQuery[],
    publishedEndpoints: EndpointResponseApi[] = [],
    publishedVersions: Record<string, EndpointVersionResponseApi[]> = {}
): ModelListRow[] {
    const rows: ModelListRow[] = []
    const endpoints = new Map<string, ModelListRow>()

    for (const view of views) {
        if (view.origin !== DataWarehouseSavedQueryOrigin.ENDPOINT || !view.endpoint) {
            rows.push(view)
            continue
        }
        const existing = endpoints.get(view.endpoint.name)
        if (existing) {
            existing.endpointVersions!.push(view)
        } else {
            const row: ModelListRow = { ...view, endpointVersions: [view] }
            endpoints.set(view.endpoint.name, row)
            rows.push(row)
        }
    }

    for (const endpoint of publishedEndpoints) {
        const snapshots = [
            {
                data: endpoint,
                version: endpoint.current_version,
                createdAt: endpoint.created_at,
                createdBy: endpoint.created_by,
            },
            ...(publishedVersions[endpoint.name] ?? []).map((version) => ({
                data: version,
                version: version.version,
                createdAt: version.version_created_at,
                createdBy: version.version_created_by,
            })),
        ]
        for (const { data, version, createdAt, createdBy } of snapshots) {
            const existing = endpoints.get(endpoint.name)
            if (existing?.endpointVersions?.some((row) => row.endpoint?.version === version)) {
                existing.endpointVersionCount = endpoint.versions_count
                continue
            }
            const row: ModelListRow = {
                id: `endpoint-${endpoint.id}-${version}`,
                name: endpoint.name,
                columns: [],
                managed_viewset_kind: null,
                latest_error: null,
                created_at: createdAt,
                created_by: createdBy
                    ? {
                          id: createdBy.id,
                          uuid: createdBy.uuid,
                          distinct_id: createdBy.distinct_id ?? '',
                          first_name: createdBy.first_name ?? '',
                          email: createdBy.email ?? '',
                      }
                    : null,
                is_materialized: data.is_materialized,
                origin: DataWarehouseSavedQueryOrigin.ENDPOINT,
                endpoint: { name: endpoint.name, version, is_current: version === endpoint.current_version },
                modelUnavailableReason: data.model_unavailable_reason,
                isEndpointPlaceholder: true,
            }
            if (existing) {
                existing.endpointVersions!.push(row)
                existing.endpointVersionCount = endpoint.versions_count
            } else {
                const parent = { ...row, endpointVersions: [row], endpointVersionCount: endpoint.versions_count }
                endpoints.set(endpoint.name, parent)
                rows.push(parent)
            }
        }
    }

    for (const row of endpoints.values()) {
        const versions = row.endpointVersions!
        versions.sort((a, b) => b.endpoint!.version - a.endpoint!.version)
        Object.assign(row, versions.find((version) => version.endpoint!.is_current) ?? versions[0])
    }
    return rows
}
