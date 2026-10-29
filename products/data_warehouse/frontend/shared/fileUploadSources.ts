import { ExternalDataSource } from '~/types'

import {
    ExternalDataSourceTypeEnumApi,
    SourceConfigResponseApi,
} from 'products/warehouse_sources/frontend/generated/api.schemas'

export const FILE_UPLOAD_SOURCE_LABEL = 'File upload'

/**
 * A file upload source imports one file a user uploaded. It has no schedule and no incremental
 * sync: PostHog starts each import itself, and the user refreshes the data by replacing the file.
 */
export function isFileUploadSource(source: Pick<ExternalDataSource, 'source_type'> | null | undefined): boolean {
    return source?.source_type === ExternalDataSourceTypeEnumApi.FileUpload
}

// The source catalog leaves out file upload sources, so their label can't come from it.
export function sourceTypeLabel(
    sourceType: string,
    availableSources: Record<string, SourceConfigResponseApi> | null | undefined
): string {
    if (sourceType === ExternalDataSourceTypeEnumApi.FileUpload) {
        return FILE_UPLOAD_SOURCE_LABEL
    }
    return availableSources?.[sourceType]?.label ?? sourceType
}
