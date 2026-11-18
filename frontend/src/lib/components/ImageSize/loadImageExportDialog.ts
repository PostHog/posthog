import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { retryImport } from 'lib/utils/retryImport'

import type { ImageSizeApi } from 'products/subscriptions/frontend/generated/api.schemas'

export async function loadImageExportDialog(onExport: (size: ImageSizeApi) => void): Promise<void> {
    try {
        const { openImageExportDialog } = await retryImport(() => import('./openImageExportDialog'))
        openImageExportDialog(onExport)
    } catch {
        lemonToast.error('Could not open the export options. Reload the page and try again.')
    }
}
