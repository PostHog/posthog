import type { PresignedUploadApi } from '../generated/api.schemas'

export class StorageUploadError extends Error {}

const STORAGE_UPLOAD_TIMEOUT_MS = 10 * 60 * 1000

export interface PostFileToStorageOptions {
    presignedUpload: PresignedUploadApi
    file: File
    /** Called with the share of the file sent so far, from 0 to 1. */
    onProgress: (fraction: number) => void
    signal?: AbortSignal
}

/**
 * Sends the file straight to object storage with the presigned POST. It uses XMLHttpRequest
 * because fetch reports no upload progress, and a transcript can be large enough to need it.
 */
export function postFileToStorage({
    presignedUpload,
    file,
    onProgress,
    signal,
}: PostFileToStorageOptions): Promise<void> {
    return new Promise((resolve, reject) => {
        const formData = new FormData()
        // The storage service checks the signed fields, and it requires them before the file part.
        for (const [key, value] of Object.entries(presignedUpload.form_fields)) {
            formData.append(key, value)
        }
        formData.append('file', file)

        const request = new XMLHttpRequest()
        request.open('POST', presignedUpload.upload_url)
        request.timeout = STORAGE_UPLOAD_TIMEOUT_MS

        request.upload.addEventListener('progress', (event) => {
            if (event.lengthComputable && event.total > 0) {
                onProgress(event.loaded / event.total)
            }
        })
        request.addEventListener('load', () => {
            if (request.status >= 200 && request.status < 300) {
                resolve()
            } else {
                reject(new StorageUploadError(`Storage refused the upload with status ${request.status}`))
            }
        })
        request.addEventListener('error', () => reject(new StorageUploadError('The upload to storage failed')))
        request.addEventListener('abort', () => reject(new StorageUploadError('The upload to storage was canceled')))
        request.addEventListener('timeout', () => reject(new StorageUploadError('The upload to storage timed out')))

        signal?.addEventListener('abort', () => request.abort())

        request.send(formData)
    })
}
