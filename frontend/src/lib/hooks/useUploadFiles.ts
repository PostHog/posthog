import api from 'lib/api'
import { useEffect, useState } from 'react'

import { MediaUploadResponse } from '~/types'

export const lazyImageBlobReducer = async (blob: Blob): Promise<Blob> => {
    const blobReducer = (await import('image-blob-reduce')).default()
    return blobReducer.toBlob(blob, { max: 2000 })
}

/**
 * The 'image-blob-reduce' library used relies on canvas.toBlob() which has slightly odd behaviour
 * It tends to convert things to png unexpectedly :'(
 * See http://kangax.github.io/jstests/toDataUrl_mime_type_test/ for a test that shows this behavior
 */
function canReduceThisBlobType(file: File): boolean {
    const supportedTypes = ['image/png', 'image/jpeg', 'image/webp']
    return supportedTypes.includes(file.type)
}

export async function uploadFile(file: File): Promise<MediaUploadResponse> {
    if (!file.type.startsWith('image/')) {
        throw new Error('File is not an image')
    }

    let fileToUpload = file
    if (canReduceThisBlobType(file)) {
        const compressedBlob = await lazyImageBlobReducer(file)
        fileToUpload = new File([compressedBlob], file.name, { type: compressedBlob.type })
    }

    const formData = new FormData()
    formData.append('image', fileToUpload)
    return await api.media.upload(formData)
}

export function useUploadFiles({
    onUpload,
    onError,
}: {
    onUpload?: (url: string, fileName: string, uploadedMediaId: string) => void
    onError: (detail: string) => void
}): {
    setFilesToUpload: (files: File[]) => void
    filesToUpload: File[]
    uploading: boolean
} {
    const [uploading, setUploading] = useState(false)
    const [filesToUpload, setFilesToUpload] = useState<File[]>([])
    useEffect(() => {
        const uploadFiles = async (): Promise<void> => {
            if (filesToUpload.length === 0) {
                setUploading(false)
                return
            }

            try {
                setUploading(true)
                const file: File = filesToUpload[0]
                const media = await uploadFile(file)
                onUpload?.(media.image_location, media.name, media.id)
            } catch (error) {
                const errorDetail = (error as any).detail || 'unknown error'
                onError(errorDetail)
            } finally {
                setUploading(false)
                setFilesToUpload([])
            }
        }
        uploadFiles().catch(console.error)
    }, [filesToUpload, onUpload, onError])

    return { setFilesToUpload, filesToUpload, uploading }
}
