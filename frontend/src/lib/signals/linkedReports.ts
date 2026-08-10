import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { signalsReportsList } from 'products/signals/frontend/generated/api'
import type { SignalReportApi, SignalSourceProductApi } from 'products/signals/frontend/generated/api.schemas'

export interface LinkedReportsQuery {
    sourceProduct: SignalSourceProductApi
    sourceId: string
    /** Also return the statuses the inbox hides by default, which are dismissed and deleted reports. */
    includeAllStatuses?: boolean
    ordering?: string
    /** Left unset the endpoint pages at 100 fully serialized reports, which no surface displays. */
    limit?: number
}

/**
 * Reports whose signals came from one source record, such as an error tracking issue or a support ticket.
 *
 * Returns an empty list instead of throwing. Every caller shows these beside the record as supplementary
 * context, and kea-loaders toasts a failed `load*` action, so a signals or ClickHouse hiccup would
 * otherwise put an error in front of someone whose page is otherwise fine.
 */
export async function fetchLinkedReports({
    sourceProduct,
    sourceId,
    includeAllStatuses,
    ordering,
    limit,
}: LinkedReportsQuery): Promise<SignalReportApi[]> {
    try {
        const response = await signalsReportsList(getCurrentTeamId().toString(), {
            source_id: sourceId,
            source_product: sourceProduct,
            ...(includeAllStatuses ? { include_all_statuses: true } : {}),
            ...(ordering ? { ordering } : {}),
            ...(limit ? { limit } : {}),
        })
        return response.results
    } catch (error) {
        console.error('Failed to load linked reports:', error)
        return []
    }
}
