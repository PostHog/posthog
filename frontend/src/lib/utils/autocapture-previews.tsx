import posthog from 'posthog-js'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { ElementType } from '~/types'

interface AutocapturedImage {
    src: string | undefined
    width: string | undefined
    height: string | undefined
}

function ensureNoTrailingSlash(origin: string): string {
    if (origin.endsWith('/')) {
        return origin.slice(0, -1)
    }
    return origin
}

function correctRelativeSrcImages(
    img: AutocapturedImage | null,
    properties?: Record<string, any>
): AutocapturedImage | null {
    if (!img) {
        return null
    }

    const isRelativePath = img.src?.startsWith('/') && !img.src?.startsWith('//')
    const propertiesHasURL = !!properties?.['$current_url']
    if (isRelativePath && propertiesHasURL) {
        try {
            const origin = new URL(properties['$current_url'])?.origin
            return {
                ...img,
                src: ensureNoTrailingSlash(origin) + img.src,
            }
        } catch (e) {
            posthog.captureException(e, { imageSource: img.src, properties: properties || {} })
            // don't show this image... something is unexpected about the URL
            return null
        }
    }
    return img
}

export function autocaptureToImage(elements: ElementType[] | undefined): null | AutocapturedImage {
    const find = elements?.find((el) => el.tag_name === 'img')
    const image = {
        src: find?.attributes?.attr__src,
        width: find?.attributes?.attr__width,
        height: find?.attributes?.attr__height,
    }
    return image.src ? image : null
}

function AutocaptureImage({ img }: { img: AutocapturedImage }): JSX.Element | null {
    if (img) {
        return (
            <div className="flex bg-primary items-center justify-center relative border-2">
                {/* Transparent grid background */}
                <div className="ImagePreview__background absolute h-full w-full" />

                <img
                    className="relative z-10 max-h-100 object-contain"
                    src={img.src}
                    alt="Autocapture image src"
                    height={img.height || 'auto'}
                    width={img.width || 'auto'}
                />
            </div>
        )
    }

    return null
}

export function AutocaptureImageTab({
    elements,
    properties,
}: {
    elements: ElementType[]
    properties?: Record<string, any>
}): JSX.Element | null {
    const img = correctRelativeSrcImages(autocaptureToImage(elements), properties)
    if (img) {
        return (
            <div className="flex bg-primary items-center justify-center relative border-2 w-full">
                <AutocaptureImage img={img} />
            </div>
        )
    }

    return null
}

export function AutocapturePreviewImage({
    elements,
    properties,
    imgPreviewHeight = '40',
}: {
    elements: ElementType[]
    properties?: Record<string, any>
    imgPreviewHeight?: string
}): JSX.Element | null {
    const img = correctRelativeSrcImages(autocaptureToImage(elements), properties)
    if (img) {
        return (
            <Tooltip title={<AutocaptureImage img={img} />}>
                <img
                    className="max-h-10"
                    src={img.src}
                    alt="Autocapture image src"
                    height={imgPreviewHeight}
                    width="auto"
                />
            </Tooltip>
        )
    }

    return null
}
