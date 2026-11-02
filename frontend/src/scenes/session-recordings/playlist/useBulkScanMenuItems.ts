import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { urls } from 'scenes/urls'

import { bulkScanLogic } from 'products/replay_vision/frontend/logics/bulkScanLogic'
import { visionQuotaLogic } from 'products/replay_vision/frontend/logics/visionQuotaLogic'
import { quotaUx } from 'products/replay_vision/frontend/utils/quotaProjection'

import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function useBulkScanMenuItems(): {
    items: LemonMenuItem[]
    disabledReason: string | undefined
    tooltip: string | undefined
} {
    const { selectedRecordingsIds } = useValues(sessionRecordingsPlaylistLogic)
    const { scanners, scannersLoading, scanning } = useValues(bulkScanLogic)
    const { scanRecordings } = useActions(bulkScanLogic)
    const { quota } = useValues(visionQuotaLogic)
    const { disabledReason: quotaDisabledReason, tooltip: quotaTooltip } = quotaUx(quota)

    const items: LemonMenuItem[] = scannersLoading
        ? [{ label: 'Loading scanners…', disabledReason: 'Loading' }]
        : scanners.length === 0
          ? [
                {
                    label: 'No scanners yet — create one',
                    onClick: () => router.actions.push(urls.replayVision()),
                    'data-attr': 'vision-bulk-scan-create-scanner',
                },
            ]
          : scanners.map((scanner) => ({
                label: scanner.name,
                onClick: () => scanRecordings(scanner.id, selectedRecordingsIds),
                'data-attr': 'vision-bulk-scan-scanner-item',
            }))

    return {
        items,
        disabledReason: scanning
            ? 'Starting scans…'
            : selectedRecordingsIds.length === 0
              ? 'Select recordings to scan'
              : quotaDisabledReason,
        tooltip: quotaTooltip,
    }
}
