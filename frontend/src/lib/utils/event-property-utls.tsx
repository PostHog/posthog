import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { ElementType } from '~/types'

interface AutocapturedImage {
    src: string | undefined
    width: string | undefined
    height: string | undefined
}

export function autocaptureToImage(elements: ElementType[]): null | AutocapturedImage {
    const find = elements.find((el) => el.tag_name === 'img')
    const image = {
        src: find?.attributes?.attr__src,
        width: find?.attributes?.attr__width,
        height: find?.attributes?.attr__height,
    }
    return image.src ? image : null
}

export function AutocaptureImage({ img }: { img: AutocapturedImage }): JSX.Element | null {
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

export function AutocaptureImageTab({ elements }: { elements: ElementType[] }): JSX.Element | null {
    const img = autocaptureToImage(elements)
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
    imgPreviewHeight = '40',
}: {
    elements: ElementType[]
    imgPreviewHeight?: string
}): JSX.Element | null {
    const img = autocaptureToImage(elements)
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
