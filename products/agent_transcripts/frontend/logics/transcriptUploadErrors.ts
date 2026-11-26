import { ApiError } from 'lib/api-error'

import type { CustomerSubmissionStateApi } from '../generated/api.schemas'
import { StorageUploadError } from './postFileToStorage'

export interface TranscriptUploadError {
    /** A server error code such as `contains_secret`, or one of the client codes below. */
    code: string
    detail: string
}

// pinned: these codes are values of the upload failed event's `code` property, next to the server's own codes
export const TOO_LARGE_CODE = 'too_large'
export const UNSUPPORTED_EXTENSION_CODE = 'unsupported_extension'
export const EMPTY_CODE = 'empty'
export const CONTAINS_SECRET_CODE = 'contains_secret'
export const STORAGE_UPLOAD_FAILED_CODE = 'storage_upload_failed'
export const UNKNOWN_ERROR_CODE = 'unknown'

const BYTES_PER_MEGABYTE = 1024 * 1024
const FIRST_SERVER_ERROR_STATUS = 500

const STORAGE_UPLOAD_FAILED_DETAIL = "Couldn't send the file. Check your connection, then upload the file again."
const UNKNOWN_ERROR_DETAIL = "Couldn't upload the transcript. Try again, and if it keeps failing, contact support."

export function formatMegabytes(bytes: number): string {
    return `${Math.floor(bytes / BYTES_PER_MEGABYTE)} MB`
}

/** Lists the extensions the way a person reads them, for example ".jsonl, .json, .md or .txt". */
export function formatExtensions(extensions: string[]): string {
    if (extensions.length <= 1) {
        return extensions.join('')
    }

    return `${extensions.slice(0, -1).join(', ')} or ${extensions[extensions.length - 1]}`
}

/** The checks the server repeats, run first so an obviously wrong file never starts an upload. */
export function checkTranscriptFile(
    file: File,
    limits: Pick<CustomerSubmissionStateApi, 'allowed_extensions' | 'max_size_bytes'>
): TranscriptUploadError | null {
    const name = file.name.toLowerCase()
    if (!limits.allowed_extensions.some((extension) => name.endsWith(extension.toLowerCase()))) {
        return {
            code: UNSUPPORTED_EXTENSION_CODE,
            detail: `Upload the transcript as a ${formatExtensions(limits.allowed_extensions)} file.`,
        }
    }

    if (file.size === 0) {
        return {
            code: EMPTY_CODE,
            detail: 'The file is empty. Choose the file that contains the conversation.',
        }
    }

    if (file.size > limits.max_size_bytes) {
        return {
            code: TOO_LARGE_CODE,
            detail: `The file is larger than ${formatMegabytes(limits.max_size_bytes)}. Choose a smaller file.`,
        }
    }

    return null
}

export function transcriptUploadErrorFrom(error: unknown): TranscriptUploadError {
    if (error instanceof StorageUploadError) {
        return { code: STORAGE_UPLOAD_FAILED_CODE, detail: STORAGE_UPLOAD_FAILED_DETAIL }
    }

    if (error instanceof ApiError && error.code) {
        return { code: error.code, detail: error.detail ?? UNKNOWN_ERROR_DETAIL }
    }

    return { code: UNKNOWN_ERROR_CODE, detail: UNKNOWN_ERROR_DETAIL }
}

export function isServerRefusal(error: unknown): boolean {
    return error instanceof ApiError && error.status !== undefined && error.status < FIRST_SERVER_ERROR_STATUS
}
