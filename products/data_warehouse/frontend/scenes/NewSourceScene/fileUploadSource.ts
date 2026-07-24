import { urls } from 'scenes/urls'

import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'

// File upload is a client-only catalog entry — it has no backend SourceConfig because an uploaded
// file becomes a self-managed DataWarehouseTable (read in place from our own bucket), not a synced
// source. `FileUpload` is deliberately not a real `ExternalDataSourceType` (there is no backend
// source of that type), so it's cast here once to reuse the shared `SourceConfig` shape and the
// wizard's connector-selection plumbing. This synthetic config drives the wizard's second step and
// the tile icon; the tiles below (one per format) all point back at it, since users look for
// "CSV", not "File upload".
export const FILE_UPLOAD_SOURCE_NAME = 'FileUpload' as unknown as ExternalDataSourceType

export type FileUploadFormat = 'csv' | 'json' | 'parquet' | 'xlsx'

export const FILE_UPLOAD_SOURCE_CONFIG: SourceConfig = {
    name: FILE_UPLOAD_SOURCE_NAME,
    label: 'File upload',
    caption: 'Upload a CSV, JSON, Parquet, or Excel file to query it in the PostHog data warehouse.',
    iconPath: '/static/services/file-upload.svg',
    releaseStatus: 'alpha',
    // The upload form is bespoke (`FileUploadSourceForm`), so no generic connection fields.
    fields: [],
}

export const FILE_UPLOAD_FORMATS: { format: FileUploadFormat; label: string; keywords: string[] }[] = [
    { format: 'csv', label: 'CSV file', keywords: ['csv', 'spreadsheet', 'comma separated', 'upload'] },
    { format: 'json', label: 'JSON file', keywords: ['json', 'ndjson', 'jsonl', 'upload'] },
    { format: 'parquet', label: 'Parquet file', keywords: ['parquet', 'pqt', 'columnar', 'upload'] },
    {
        format: 'xlsx',
        label: 'Excel file',
        keywords: ['excel', 'xlsx', 'xls', 'xlsm', 'spreadsheet', 'workbook', 'upload'],
    },
]

export function fileUploadSourceUrl(format: FileUploadFormat): string {
    const url = urls.dataWarehouseSourceNew(FILE_UPLOAD_SOURCE_NAME)
    return `${url}${url.includes('?') ? '&' : '?'}format=${format}`
}
