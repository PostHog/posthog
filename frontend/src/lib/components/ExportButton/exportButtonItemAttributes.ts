import { ExporterFormat, OnlineExportContext } from '~/types'

import type { ExportButtonItem } from './ExportButton'

interface ExportButtonItemAttributes {
    extension: string
    target: string
    body: string
}

export function exportButtonItemAttributes(item: ExportButtonItem): ExportButtonItemAttributes {
    const extension = (
        Object.keys(ExporterFormat).find(
            (key) => ExporterFormat[key as keyof typeof ExporterFormat] === item.export_format
        ) ?? item.export_format
    ).toLowerCase()

    if (item.insight) {
        return { extension, target: `insight-${item.insight}`, body: '' }
    }
    if (item.dashboard) {
        return { extension, target: `dashboard-${item.dashboard}`, body: '' }
    }
    if ('path' in (item.export_context || {})) {
        const context = item.export_context as OnlineExportContext
        return { extension, target: context?.path || 'unknown', body: context?.body || 'unknown' }
    }
    return { extension, target: 'unknown', body: '' }
}
