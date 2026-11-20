import type { ImageSizeApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { imageSizeError } from './imageSizeUtils'

export async function resizeImageBlob(blob: Blob, size: ImageSizeApi): Promise<Blob> {
    if (size.width == null && size.height == null) {
        return blob
    }
    const error = imageSizeError(size)
    if (error) {
        throw new Error(error)
    }
    const image = await createImageBitmap(blob)
    try {
        const width = size.width ?? Math.max(1, Math.min(4000, Math.round((image.width * size.height!) / image.height)))
        const height = size.height ?? Math.max(1, Math.min(5000, Math.round((image.height * width) / image.width)))
        const scale = Math.min(width / image.width, height / image.height)
        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        const context = canvas.getContext('2d')
        if (!context) {
            throw new Error('Could not resize the image.')
        }
        context.drawImage(image, 0, 0, 1, 1, 0, 0, width, height)
        context.drawImage(
            image,
            (width - image.width * scale) / 2,
            (height - image.height * scale) / 2,
            image.width * scale,
            image.height * scale
        )
        return await new Promise<Blob>((resolve, reject) =>
            canvas.toBlob(
                (result) => (result ? resolve(result) : reject(new Error('Could not resize the image.'))),
                'image/png'
            )
        )
    } finally {
        image.close()
    }
}
