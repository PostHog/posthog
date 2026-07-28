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

// Callers default to images only; pass a wider list (e.g. 'application/pdf') to opt in.
const IMAGE_ONLY_CONTENT_TYPES = ['image/*']

// Browsers report an empty or inconsistent type for these files depending on the OS
// (.md especially, but also .pdf/.csv on some platforms). The upload endpoint keys on
// content type, so map the extension to a known type as a fallback.
const EXTENSION_CONTENT_TYPES: Record<string, string> = {
    md: 'text/markdown',
    markdown: 'text/markdown',
    txt: 'text/plain',
    csv: 'text/csv',
    pdf: 'application/pdf',
}

function extensionContentType(file: File): string {
    const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
    return EXTENSION_CONTENT_TYPES[extension] ?? ''
}

// Resolve against the allowlist: trust the browser's type when it's allowed, otherwise
// fall back to the extension. This covers both an empty type and a "wrong" type the OS
// reports for a file the picker accepted (e.g. .csv as application/vnd.ms-excel).
function resolveContentType(file: File, allowedContentTypes: string[]): string {
    if (file.type && isContentTypeAllowed(file.type, allowedContentTypes)) {
        return file.type
    }
    const fromExtension = extensionContentType(file)
    if (fromExtension && isContentTypeAllowed(fromExtension, allowedContentTypes)) {
        return fromExtension
    }
    return file.type
}

function isContentTypeAllowed(fileType: string, allowedContentTypes: string[]): boolean {
    return allowedContentTypes.some((allowed) =>
        allowed.endsWith('/*') ? fileType.startsWith(allowed.slice(0, -1)) : fileType === allowed
    )
}

export async function uploadFile(
    file: File,
    allowedContentTypes: string[] = IMAGE_ONLY_CONTENT_TYPES
): Promise<MediaUploadResponse> {
    const contentType = resolveContentType(file, allowedContentTypes)
    if (!isContentTypeAllowed(contentType, allowedContentTypes)) {
        throw new Error('File type is not supported')
    }

    let fileToUpload = file
    if (canReduceThisBlobType(file)) {
        const compressedBlob = await lazyImageBlobReducer(file)
        fileToUpload = new File([compressedBlob], file.name, { type: compressedBlob.type })
    } else if (contentType !== file.type) {
        // Re-stamp the inferred type so the multipart part carries it to the backend.
        fileToUpload = new File([file], file.name, { type: contentType })
    }

    const formData = new FormData()
    formData.append('image', fileToUpload)
    return await api.media.upload(formData)
}

export function useUploadFiles({
    onUpload,
    onError,
    allowedContentTypes,
}: {
    onUpload?: (url: string, fileName: string, uploadedMediaId: string, contentType: string) => void
    onError: (detail: string) => void
    allowedContentTypes?: string[]
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
                const media = await uploadFile(file, allowedContentTypes)
                onUpload?.(
                    media.image_location,
                    media.name,
                    media.id,
                    resolveContentType(file, allowedContentTypes ?? IMAGE_ONLY_CONTENT_TYPES)
                )
            } catch (error) {
                const errorDetail = (error as any).detail || (error as any).message || 'unknown error'
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
