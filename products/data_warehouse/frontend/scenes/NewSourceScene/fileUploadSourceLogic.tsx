import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'

import type { fileUploadSourceLogicType } from './fileUploadSourceLogicType'
import { FILE_UPLOAD_SOURCE_NAME, FileUploadFormat } from './sourceCatalogLogic'

// Mirrors MAX_FILE_UPLOAD_SIZE_BYTES on the backend. Checked here too so an oversized file fails
// instantly instead of after uploading 50MB+ only to be rejected.
export const MAX_FILE_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024

export const FILE_UPLOAD_ACCEPT: Record<FileUploadFormat, string> = {
    csv: '.csv',
    json: '.json,.ndjson',
    parquet: '.parquet',
}

const HOGQL_TABLE_NAME_REGEX = /^[a-zA-Z_][a-zA-Z0-9_]*$/

export interface FileUploadForm {
    files: File[]
    table_name: string
    file_format: FileUploadFormat
}

export function deriveTableName(filename: string): string {
    const withoutExtension = filename.replace(/\.[^.]+$/, '')
    const slug = withoutExtension
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/_+$/, '')
    if (!slug) {
        return 'uploaded_file'
    }
    return /^[0-9]/.test(slug) ? `_${slug}` : slug
}

export function parseFileUploadFormat(value: string | undefined): FileUploadFormat | null {
    const normalized = value?.toLowerCase()
    return normalized === 'csv' || normalized === 'json' || normalized === 'parquet' ? normalized : null
}

export function fileUploadFormErrors({ files, table_name }: Partial<FileUploadForm>): Record<string, unknown> {
    const file = files?.[0]
    return {
        files: !file
            ? 'Please choose a file to upload.'
            : file.size > MAX_FILE_UPLOAD_SIZE_BYTES
              ? 'This file is larger than 50MB. For bigger files, connect the bucket they live in as a self-managed source instead.'
              : undefined,
        table_name: !table_name
            ? 'Please enter a table name.'
            : !HOGQL_TABLE_NAME_REGEX.test(table_name)
              ? 'Table names must start with a letter or underscore and contain only letters, numbers, and underscores.'
              : undefined,
    }
}

export const fileUploadSourceLogic = kea<fileUploadSourceLogicType>([
    path(['products', 'dataWarehouse', 'fileUploadSourceLogic']),
    connect(() => ({
        actions: [databaseTableListLogic, ['loadDatabase']],
    })),
    actions({
        selectFiles: (files: File[]) => ({ files }),
        setTableName: (tableName: string) => ({ tableName }),
        setFileFormat: (fileFormat: FileUploadFormat) => ({ fileFormat }),
    }),
    reducers({
        // Once the user types their own table name we stop overwriting it when they swap the file.
        tableNameEdited: [false, { setTableName: () => true }],
    }),
    forms(({ actions }) => ({
        fileUpload: {
            defaults: {
                files: [] as File[],
                table_name: '',
                file_format: parseFileUploadFormat(router.values.searchParams.format) ?? 'csv',
            } as FileUploadForm,
            errors: fileUploadFormErrors,
            submit: async ({ files, table_name, file_format }) => {
                const file = files[0]
                // The form's `errors` already block submission, but a stale/oversized file can only
                // be reported as a toast — the button is what the user is looking at.
                if (!file) {
                    lemonToast.error('Please choose a file to upload.')
                    return
                }
                if (file.size > MAX_FILE_UPLOAD_SIZE_BYTES) {
                    lemonToast.error('This file is larger than the 50MB upload limit.')
                    return
                }

                const formData = new FormData()
                formData.append('file', file)
                formData.append('file_format', file_format)

                let upload
                try {
                    upload = await api.externalDataSources.uploadFile(formData)
                } catch (e: any) {
                    lemonToast.error(e.data?.message ?? e.message ?? 'Could not upload the file.')
                    return
                }

                try {
                    await api.externalDataSources.create({
                        source_type: FILE_UPLOAD_SOURCE_NAME,
                        prefix: '',
                        created_via: 'web',
                        payload: {
                            table_name,
                            file_format,
                            upload_id: upload.upload_id,
                            filename: upload.filename,
                            schemas: [{ name: table_name, should_sync: true, sync_type: 'full_refresh' }],
                        },
                    })
                } catch (e: any) {
                    lemonToast.error(e.data?.message ?? e.message ?? 'Could not create the source.')
                    return
                }

                lemonToast.success(`Table ${table_name} is being imported`)
                actions.loadDatabase()
                router.actions.replace(urls.sources())
            },
        },
    })),
    listeners(({ actions, values }) => ({
        selectFiles: ({ files }) => {
            actions.setFileUploadValue('files', files)
            const file = files[0]
            if (file && !values.tableNameEdited) {
                actions.setFileUploadValue('table_name', deriveTableName(file.name))
            }
        },
        setTableName: ({ tableName }) => {
            actions.setFileUploadValue('table_name', tableName)
        },
        setFileFormat: ({ fileFormat }) => {
            actions.setFileUploadValue('file_format', fileFormat)
        },
    })),
    urlToAction(({ actions }) => ({
        [urls.dataWarehouseSourceNew()]: (_, searchParams) => {
            const format = parseFileUploadFormat(searchParams.format)
            if (format) {
                actions.setFileFormat(format)
            }
        },
    })),
])
