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

    const response = await api.create('api/projects/@current/uploaded_media', formData)
    return response
}

export async function createObjectMediaPreview(
    uploadedMediaId: string,
    eventDefinitionId: string
): Promise<ObjectMediaPreview> {
    const response = await api.create('api/projects/@current/object_media_previews', {
        uploaded_media_id: uploadedMediaId,
        event_definition_id: eventDefinitionId,
    })
    return response
}

export async function convertBlobToPNG(blob: Blob): Promise<Blob> {
    return new Promise((resolve, reject) => {
        const img = new Image()
        const url = URL.createObjectURL(blob)

        img.onload = () => {
            const canvas = document.createElement('canvas')
            canvas.width = img.width
            canvas.height = img.height

            const ctx = canvas.getContext('2d')
            if (!ctx) {
                URL.revokeObjectURL(url)
                reject(new Error('Could not get canvas context'))
                return
            }

            ctx.drawImage(img, 0, 0)
            URL.revokeObjectURL(url)

            canvas.toBlob(
                (pngBlob) => {
                    if (pngBlob) {
                        resolve(pngBlob)
                    } else {
                        reject(new Error('Failed to convert image to PNG'))
                    }
                },
                'image/png',
                1.0
            )
        }

        img.onerror = () => {
            URL.revokeObjectURL(url)
            reject(new Error('Failed to load image'))
        }

        img.src = url
    })
}
