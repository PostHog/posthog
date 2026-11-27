import { useEffect, useMemo, useState } from 'react'

import { uploadFile } from 'lib/hooks/useUploadFiles'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeProps, NotebookNodeType } from '../types'

const MAX_DEFAULT_HEIGHT = 1000

const Component = ({ attributes, updateAttributes }: NotebookNodeProps<NotebookNodeImageAttributes>): JSX.Element => {
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

    const imageSource = useMemo(
        () => (src ? src : file && file.type ? URL.createObjectURL(file) : undefined),
        [src, file]
    )

    useEffect(() => {
        if (!file && !src) {
            setError('Image not found')
        }
    }, [src, file])

    if (error) {
        return (
            <div className="flex flex-1 items-center justify-center">
                <LemonBanner type="error">{error}</LemonBanner>
            </div>
        )
    }

    return (
        <>
            <img
                src={imageSource}
                alt="user uploaded file"
                className="w-full object-contain"
                style={{ height: height ? '100%' : 'auto', maxHeight: height ? undefined : MAX_DEFAULT_HEIGHT }}
            />
            {uploading ? <SpinnerOverlay className="text-3xl" /> : null}
        </>
    )
}

type NotebookNodeImageAttributes = {
    file?: File
    src?: string
}

export const NotebookNodeImage = createPostHogWidgetNode<NotebookNodeImageAttributes>({
    nodeType: NotebookNodeType.Image,
    titlePlaceholder: 'Image',
    Component,
    serializedText: (attrs) => {
        // TODO file is null when this runs... should it be?
        return attrs?.file?.name || ''
    },
    heightEstimate: 'auto',
    minHeight: 100,
    resizeable: true,
    expandable: false,
    autoHideMetadata: true,
    attributes: {
        file: {},
        src: {},
    },
})
