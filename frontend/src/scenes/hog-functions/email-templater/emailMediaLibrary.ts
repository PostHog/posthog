import posthog from 'posthog-js'
import type { Editor } from 'react-email-editor'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { uploadedMediaCreate, uploadedMediaDestroy, uploadedMediaList } from '~/generated/core/api'
import { UploadedMediaListPurpose } from '~/generated/core/api.schemas'
import type { UploadedMediaApi } from '~/generated/core/api.schemas'

const UPLOAD_FAILED_MESSAGE = "Couldn't upload this image. Try again."
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
            try {
                const media = await uploadedMediaCreate(projectId, { image, purpose: UploadedMediaListPurpose.Email })
                // pinned: analytics event name and properties, renaming breaks dashboards
                posthog.capture('email media library image uploaded', { success: true })
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
