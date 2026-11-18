import type { ImageSizeApi } from 'products/subscriptions/frontend/generated/api.schemas'

export function imageSizeError(size: ImageSizeApi | undefined): string | undefined {
    if (size?.width != null && (!Number.isInteger(size.width) || size.width < 320 || size.width > 4000)) {
        return 'Enter a width between 320 and 4,000 pixels.'
    }
    if (size?.height != null && (!Number.isInteger(size.height) || size.height < 200 || size.height > 5000)) {
        return 'Enter a height between 200 and 5,000 pixels.'
    }
}

export function imageSizeFromParams(params: URLSearchParams): ImageSizeApi {
    const size = {
        width: params.has('width') ? Number(params.get('width')) : undefined,
        height: params.has('height') ? Number(params.get('height')) : undefined,
    }
    return imageSizeError(size) ? {} : size
}
