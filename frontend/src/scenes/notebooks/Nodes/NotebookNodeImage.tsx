import { ReactEventHandler, useEffect, useState } from 'react'

import { uploadFile } from 'lib/hooks/useUploadFiles'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeProps, NotebookNodeType } from '../types'

const MAX_DEFAULT_HEIGHT = 1000

type NotebookNodeImageAttributes = {
    file?: File
    src?: string
}

export const NotebookNodeImageComponent = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodeImageAttributes>): JSX.Element => {
    const { file, src, height } = attributes
    const [uploading, setUploading] = useState(false)
    const [error, setError] = useState<string>()

    useEffect(() => {
        if (file) {
            if (!file.type) {
                updateAttributes({ file: undefined })
                return
            }

            setUploading(true)

            uploadFile(file)
                .then(async (media) => {
                    updateAttributes({
                        file: undefined,
                        src: media.image_location,
                    })
                })
                .catch(() => {
                    setError('Error uploading image')
                })
                .finally(() => {
                    setUploading(false)
                })
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [file])

    const [objectUrl, setObjectUrl] = useState<string | undefined>(undefined)

    useEffect(() => {
        if (!file || !file.type || src) return

        const url = URL.createObjectURL(file)
        setObjectUrl(url)

        return () => {
            URL.revokeObjectURL(url)
            setObjectUrl(undefined)
        }
    }, [file, src])

    const imageSource = src || objectUrl

    useEffect(() => {
        if (!file && !src) {
            setError('Image not found')
        }
    }, [src, file])

    const onImageLoad: ReactEventHandler<HTMLImageElement> = (e): void => {
        if (!height) {
            // Set the height value to match the image if it isn't already set
            updateAttributes({
                height: Math.min(e.currentTarget.naturalHeight, MAX_DEFAULT_HEIGHT),
            })
        }
    }

    if (error) {
        return (
            <div className="flex flex-1 items-center justify-center">
                <LemonBanner type="error">{error}</LemonBanner>
            </div>
        )
    }

    return (
        <>
            <img src={imageSource} onLoad={onImageLoad} alt="user uploaded file" />
            {uploading ? <SpinnerOverlay className="text-3xl" /> : null}
        </>
    )
}

export const NotebookNodeImage = createPostHogWidgetNode<NotebookNodeImageAttributes>({
    nodeType: NotebookNodeType.Image,
    titlePlaceholder: 'Image',
    Component: NotebookNodeImageComponent,
    serializedText: (attrs) => {
        // TODO file is null when this runs... should it be?
        return attrs?.file?.name || ''
    },
    heightEstimate: 400,
    minHeight: 100,
    resizeable: true,
    expandable: false,
    autoHideMetadata: true,
    attributes: {
        file: {},
        src: {},
    },
})
