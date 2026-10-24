import { ExporterFormat, OnlineExportContext } from '~/types'

import type { TriggerExportProps } from './exporter'

export interface ExportItemAttributes {
    /** File extension for the format, for example "png". */
    extension: string
    /** Value for `data-ph-capture-attribute-export-target`. */
    target: string
    /** Value for `data-ph-capture-attribute-export-body`, or null when the export has no body. */
    body: string | null
}

/** The extension and the autocapture attributes that an export menu row carries. */
export function exportItemAttributes(triggerExportProps: TriggerExportProps): ExportItemAttributes {
    const extension = (
        Object.keys(ExporterFormat).find(
            (key) => ExporterFormat[key as keyof typeof ExporterFormat] === triggerExportProps.export_format
        ) ?? triggerExportProps.export_format
    ).toLowerCase()

    let target: string
    let body = ''
    if (triggerExportProps.insight) {
        target = `insight-${triggerExportProps.insight}`
    } else if (triggerExportProps.dashboard) {
        target = `dashboard-${triggerExportProps.dashboard}`
    } else if ('path' in (triggerExportProps.export_context || {})) {
        target = (triggerExportProps.export_context as OnlineExportContext)?.path || 'unknown'
        body = (triggerExportProps.export_context as OnlineExportContext)?.body || 'unknown'
    } else {
        target = 'unknown'
    }

    return { extension, target, body: body.length ? JSON.stringify(body) : null }
}
