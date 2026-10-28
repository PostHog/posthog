import type { LemonTagType } from '@posthog/lemon-ui'

import type { ExternalDataDestinationStatusEnumApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

export const DESTINATION_STATUS_TAGS: Record<
    ExternalDataDestinationStatusEnumApi,
    { label: string; type: LemonTagType }
> = {
    healthy: { label: 'Healthy', type: 'success' },
    failing: { label: 'Failing', type: 'warning' },
    paused: { label: 'Paused', type: 'danger' },
}
