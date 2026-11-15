import posthog from 'posthog-js'
import type { Editor } from 'react-email-editor'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { uploadedMediaCreate, uploadedMediaDestroy, uploadedMediaList } from '~/generated/core/api'
import { UploadedMediaListPurpose } from '~/generated/core/api.schemas'
import type { UploadedMediaApi } from '~/generated/core/api.schemas'

const UPLOAD_FAILED_MESSAGE = "Couldn't upload this image. Try again."
const RESIZE_FAILED_MESSAGE =
    "Couldn't resize this image automatically, and it's over the 4 MB limit. Use a smaller image and try again."
const MAX_UPLOAD_BYTES = 4 * 1024 * 1024
// The last size always fits: 800x800 is under 4 MB even with no compression at all.
const RESIZE_LONGEST_SIDES_PX = [2000, 1600, 1200, 800]
const RESIZED_JPEG_QUALITY = 0.85
// A decoded image takes 4 bytes per pixel, so this keeps resizing under about 400 MB of memory.
const MAX_DECODED_PIXELS = 100_000_000
// Unlayer passes `page` but no page size, so the provider decides how many images a page holds.
const UPLOADS_PAGE_SIZE = 20

/** The image shape Unlayer's Uploads tab renders. */
export interface UnlayerUploadsImage {
    id: string
    location: string
    width: number
    height: number
    contentType: string
    size?: number
    source: 'user'
}

export interface UnlayerUploadsPage {
    page: number
    perPage?: number
    searchText?: string
}

export interface UnlayerUploadsPageMeta {
    hasMore: boolean
    page: number
    perPage: number
    total: number
}

/** What Unlayer's `image` upload callback accepts as progress, success, or failure. */
export interface UnlayerImageUploadResult {
    progress?: number
    url?: string
    id?: string
    filename?: string
    width?: number | null
    height?: number | null
    abort?: boolean
    error?: string
}

export function toUnlayerUploadsImage(media: UploadedMediaApi): UnlayerUploadsImage {
    return {
        id: media.id,
        location: media.url,
        // Images uploaded before dimensions were recorded have none. Unlayer reads the real size
        // from the image when it is placed, so 0 only affects the thumbnail grid.
        width: media.width ?? 0,
        height: media.height ?? 0,
        contentType: media.content_type ?? '',
        size: media.size_bytes ?? undefined,
        source: 'user',
    }
}

function uploadErrorMessage(error: unknown): string {
    return error instanceof ApiError && error.detail ? error.detail : UPLOAD_FAILED_MESSAGE
}

function hasTransparency(context: CanvasRenderingContext2D, width: number, height: number): boolean {
    try {
        const { data } = context.getImageData(0, 0, width, height)
        for (let alpha = 3; alpha < data.length; alpha += 4) {
            if (data[alpha] !== 255) {
                return true
            }
        }
        return false
    } catch {
        // Privacy-focused browsers can block reading pixels. PNG is safe for either case.
        return true
    }
}

// An image element reports its size once loaded, before the browser decodes its pixels.
async function readPixelCount(image: File): Promise<number> {
    const url = URL.createObjectURL(image)
    try {
        return await new Promise<number>((resolve, reject) => {
            const element = new Image()
            element.onload = () => resolve(element.naturalWidth * element.naturalHeight)
            element.onerror = () => reject(new Error('Image could not be read'))
            element.src = url
        })
    } finally {
        URL.revokeObjectURL(url)
    }
}

async function assertCanBeResized(image: File): Promise<void> {
    // Drawing a GIF to a canvas keeps only its first frame.
    if (image.type === 'image/gif') {
        throw new Error('GIFs cannot be resized')
    }
    if ((await readPixelCount(image)) > MAX_DECODED_PIXELS) {
        throw new Error('Image has too many pixels to resize safely')
    }
}

async function shrinkToUploadLimit(image: File): Promise<File> {
    await assertCanBeResized(image)
    const bitmap = await createImageBitmap(image)
    try {
        const canvas = document.createElement('canvas')
        const context = canvas.getContext('2d')
        if (!context) {
            throw new Error('Canvas is not available')
        }
        const originalLongestSide = Math.max(bitmap.width, bitmap.height)
        let outputType: string | undefined
        for (const longestSide of RESIZE_LONGEST_SIDES_PX) {
            const scale = Math.min(1, longestSide / originalLongestSide)
            canvas.width = Math.round(bitmap.width * scale)
            canvas.height = Math.round(bitmap.height * scale)
            context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
            // JPEG would turn transparent areas black, so it's only for images without any.
            outputType ??=
                image.type !== 'image/jpeg' && hasTransparency(context, canvas.width, canvas.height)
                    ? 'image/png'
                    : 'image/jpeg'
            const type = outputType
            const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, type, RESIZED_JPEG_QUALITY))
            if (blob && blob.size <= MAX_UPLOAD_BYTES) {
                const name = image.name.replace(/(\.[^.]+)?$/, type === 'image/png' ? '.png' : '.jpg')
                return new File([blob], name, { type })
            }
        }
    } finally {
        bitmap.close()
    }
    throw new Error('Image is still over the upload limit after resizing')
}

/**
 * Backs Unlayer's Uploads tab with the team's email media library, so uploads land in our storage
 * and every template on the team can reuse them.
 */
export function registerEmailMediaLibrary(editor: Editor, projectId: string): void {
    editor.registerProvider(
        'userUploads',
        async (
            { page, perPage = UPLOADS_PAGE_SIZE, searchText }: UnlayerUploadsPage,
            done: (images: UnlayerUploadsImage[], meta: UnlayerUploadsPageMeta) => void
        ) => {
            const search = searchText?.trim() || undefined
            if (page === 1) {
                // pinned: analytics event name and properties, renaming breaks dashboards
                posthog.capture('email media library viewed', { searched: !!search })
            }
            try {
                const response = await uploadedMediaList(projectId, {
                    purpose: UploadedMediaListPurpose.Email,
                    limit: perPage,
                    offset: (page - 1) * perPage,
                    search,
                })
                done(response.results.map(toUnlayerUploadsImage), {
                    hasMore: !!response.next,
                    page,
                    perPage,
                    total: response.count,
                })
            } catch {
                lemonToast.error("Couldn't load your images. Try again.")
                done([], { hasMore: false, page, perPage, total: 0 })
            }
        }
    )

    editor.registerCallback(
        'image',
        async (file: { attachments: File[] }, done: (result: UnlayerImageUploadResult) => void) => {
            const image = file.attachments[0]
            if (!image) {
                done({ abort: true })
                return
            }
            done({ progress: 10 })
            let imageToUpload = image
            if (image.size > MAX_UPLOAD_BYTES) {
                try {
                    imageToUpload = await shrinkToUploadLimit(image)
                } catch {
                    posthog.capture('email media library image uploaded', {
                        success: false,
                        error_code: 'resize_failed',
                    })
                    done({ error: RESIZE_FAILED_MESSAGE })
                    return
                }
            }
            try {
                const media = await uploadedMediaCreate(projectId, {
                    image: imageToUpload,
                    purpose: UploadedMediaListPurpose.Email,
                })
                // pinned: analytics event name and properties, renaming breaks dashboards
                posthog.capture('email media library image uploaded', {
                    success: true,
                    resized: imageToUpload !== image,
                })
                done({
                    progress: 100,
                    url: media.image_location,
                    id: media.id,
                    filename: media.name,
                    width: media.width,
                    height: media.height,
                })
            } catch (error) {
                posthog.capture('email media library image uploaded', {
                    success: false,
                    error_code: error instanceof ApiError ? (error.code ?? error.status) : null,
                })
                done({ error: uploadErrorMessage(error) })
            }
        }
    )

    editor.registerCallback('image:removed', async ({ id }: { id: string | number }, done: () => void) => {
        try {
            await uploadedMediaDestroy(projectId, String(id))
            // pinned: analytics event name, renaming breaks dashboards
            posthog.capture('email media library image removed')
        } catch (error) {
            // A 404 means it is already gone from the library, which is what the user asked for.
            if (!(error instanceof ApiError && error.status === 404)) {
                lemonToast.error("Couldn't remove this image. Try again.")
                return
            }
        }
        done()
    })
}
