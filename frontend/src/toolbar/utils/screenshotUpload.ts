import api from 'lib/api'

import type { ObjectMediaPreview } from '~/types'

export interface UploadedMediaResponse {
    id: string
    image_location: string
    name: string
}

export async function uploadScreenshotImage(blob: Blob, filename: string): Promise<UploadedMediaResponse> {
    const formData = new FormData()
    formData.append('image', blob, filename)

    return await api.create('api/projects/@current/uploaded_media', formData)
}

export async function createObjectMediaPreview(
    uploadedMediaId: string,
    eventDefinitionId: string
): Promise<ObjectMediaPreview> {
    return await api.create('api/projects/@current/object_media_previews', {
        uploaded_media_id: uploadedMediaId,
        event_definition_id: eventDefinitionId,
    })
}
