import { getTextFromFile } from 'lib/utils/file-utils'

import type { SourceFieldConfig } from 'products/data_warehouse/frontend/types'

type FileUploadField = Extract<SourceFieldConfig, { type: 'file-upload' }>

export interface UploadedFileField {
    field: FileUploadField
    /** The object the field's value sits on, so the caller can write the parsed file back to it. */
    container: Record<string, any>
    /** The file the user picked. */
    file: File
}

export const clonePayloadPreservingFiles = (value: unknown): unknown => {
    if (value instanceof File) {
        return value
    }

    if (Array.isArray(value)) {
        return value.map((item) => clonePayloadPreservingFiles(item))
    }

    if (value instanceof Date) {
        return new Date(value.getTime())
    }
    if (value && typeof value === 'object' && value.constructor === Object) {
        return Object.fromEntries(
            Object.entries(value as Record<string, unknown>).map(([key, nestedValue]) => [
                key,
                clonePayloadPreservingFiles(nestedValue),
            ])
        )
    }

    return value
}

/**
 * Every file the user picked, with the object its value sits on. A file-upload field declared
 * inside a select option or a switch group renders in a kea `Group`, so its value lands under the
 * parent field's name (`auth_type.key_file`) rather than at the top of the payload.
 *
 * A field whose value is not a fresh `File` is left out: on the configuration form the stored,
 * already-parsed contents of an earlier upload sit under the same name.
 */
export const findUploadedFiles = (fields: SourceFieldConfig[], valueObj: Record<string, any>): UploadedFileField[] => {
    const uploads: UploadedFileField[] = []

    for (const field of fields) {
        if (field.type === 'file-upload') {
            const file = valueObj[field.name]?.[0]
            if (file instanceof File) {
                uploads.push({ field, container: valueObj, file })
            }
            continue
        }

        const nestedValue = valueObj[field.name]
        const canDescend = !!nestedValue && typeof nestedValue === 'object' && !Array.isArray(nestedValue)

        // A disabled group's stored file must not be sent; the backend string form comes from an
        // earlier config, the same as the form validation handles.
        const groupEnabled = canDescend && !!nestedValue.enabled && nestedValue.enabled !== 'False'

        if (field.type === 'switch-group' && groupEnabled) {
            uploads.push(...findUploadedFiles(field.fields, nestedValue))
            continue
        }

        if (field.type === 'select' && canDescend) {
            const selection = nestedValue.selection ?? field.defaultValue
            const selectedFields = field.options.find((option) => option.value === selection)?.fields ?? []
            uploads.push(...findUploadedFiles(selectedFields, nestedValue))
        }
    }

    return uploads
}

export const readJsonFile = async (file: File): Promise<Record<string, unknown>> => {
    const parsed: unknown = JSON.parse(await getTextFromFile(file))
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('The uploaded JSON file must contain an object')
    }
    return parsed as Record<string, unknown>
}
