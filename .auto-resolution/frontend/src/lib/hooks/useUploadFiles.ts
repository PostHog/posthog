import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import api from 'lib/api'

import { MediaUploadResponse } from '~/types'

export const lazyImageBlobReducer = async (blob: Blob): Promise<Blob> => {
    try {
        const blobReducer = (await import('image-blob-reduce')).default()
        return await blobReducer.toBlob(blob, { max: 2000 })
    } catch {
        // Fallback to simple resize for privacy-focused browsers (e.g. Brave)
        try {
            return await simpleImageResize(blob)
        } catch (error) {
            posthog.captureException(
                new Error('Image compression fallback failed', {
                    cause: error,
                })
            )
            // Final fallback to original blob
            return blob
        }
    }
}

/**
 * Simple image resize fallback that avoids Canvas fingerprinting APIs
 * Uses createImageBitmap + OffscreenCanvas
 */
async function simpleImageResize(blob: Blob): Promise<Blob> {
    if (typeof createImageBitmap === 'undefined' || typeof OffscreenCanvas === 'undefined') {
        throw new Error('OffscreenCanvas APIs not available')
    }

    const bitmap = await createImageBitmap(blob)

    // Only resize if image is larger than 2000px or file is > 2MB
    if (bitmap.width <= 2000 && bitmap.height <= 2000 && blob.size <= 2 * 1024 * 1024) {
        bitmap.close()
        return blob
    }

    // Calculate new dimensions (max 2000px, maintain aspect ratio)
    const scale = Math.min(2000 / bitmap.width, 2000 / bitmap.height)
    const newWidth = Math.floor(bitmap.width * scale)
    const newHeight = Math.floor(bitmap.height * scale)

    // Create OffscreenCanvas and resize
    const canvas = new OffscreenCanvas(newWidth, newHeight)
    const ctx = canvas.getContext('2d')
    if (!ctx) {
        throw new Error('Failed to get 2D context')
    }

    ctx.drawImage(bitmap, 0, 0, newWidth, newHeight)
    bitmap.close()

    // Convert to JPEG with compression
    return await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.8 })
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
    const uploadInProgressRef = useRef(false)

    useEffect(() => {
        const uploadFiles = async (): Promise<void> => {
            if (filesToUpload.length === 0 || uploadInProgressRef.current) {
                setUploading(false)
                return
            }

            try {
                uploadInProgressRef.current = true
                setUploading(true)
                const file: File = filesToUpload[0]
                const media = await uploadFile(file)
                onUpload?.(media.image_location, media.name, media.id)
            } catch (error) {
                const errorDetail = (error as any).detail || 'unknown error'
                onError(errorDetail)
            } finally {
                uploadInProgressRef.current = false
                setUploading(false)
                setFilesToUpload([])
            }
        }
        uploadFiles().catch(console.error)
    }, [filesToUpload]) // oxlint-disable-line react-hooks/exhaustive-deps

    return { setFilesToUpload, filesToUpload, uploading }
}
