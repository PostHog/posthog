import { urls } from 'scenes/urls'

import type { EndpointHealthApi } from './generated/api.schemas'

/**
 * The tracing operation an endpoint row counts. A "<METHOD> <route>" row filters on the raw span
 * name plus its route attribute, since the method alone would match every route the service serves.
 */
export function endpointOperationUrl(
    row: Pick<EndpointHealthApi, 'service_name' | 'endpoint' | 'span_name' | 'route_attribute' | 'route'>,
    dateRange?: { date_from?: string | null; date_to?: string | null }
): string {
    const route = row.route_attribute && row.route ? { attribute: row.route_attribute, value: row.route } : null
    return urls.tracingOperation(row.service_name, row.span_name || row.endpoint, dateRange, route)
}
