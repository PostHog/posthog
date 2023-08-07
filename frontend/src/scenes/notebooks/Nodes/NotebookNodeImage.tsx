import { api } from '@posthog/apps-common'
import { NodeViewProps } from '@tiptap/core'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { lazyImageBlobReducer } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { ReactEventHandler, useEffect, useState } from 'react'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { MediaUploadResponse, NotebookNodeType } from '~/types'

const MAX_DEFAULT_HEIGHT = 1000

async function uploadFile(file: File): Promise<MediaUploadResponse> {
    if (!file.type.startsWith('image/')) {
        throw new Error('File is not an image')
    }

    const compressedBlob = await lazyImageBlobReducer(file)
    const fileToUpload = new File([compressedBlob], file.name, { type: compressedBlob.type })

    const formData = new FormData()
    formData.append('image', fileToUpload)
    const media = await api.media.upload(formData)

    return media
}

const Component = (props: NodeViewProps): JSX.Element => {
    const { file, src, height } = props.node.attrs

    const [uploading, setUploading] = useState(false)
    const [error, setError] = useState<string>()

    useEffect(() => {
        if (file) {
            // Start uploading
            setUploading(true)

            uploadFile(file)
                .then((media) => {
                    props.updateAttributes({
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
    }, [file])

    useEffect(() => {
        if (!file && !src) {
            setError('Image not found')
        }
    }, [src, file])

    const onImageLoad: ReactEventHandler<HTMLImageElement> = (e): void => {
        if (!height) {
            // Set the height value to match the image if it isn't already set
            props.updateAttributes({
                height: Math.min(e.currentTarget.naturalHeight, MAX_DEFAULT_HEIGHT),
            })
        }
    }

    if (uploading) {
        return (
            <div>
                <Spinner />
            </div>
        )
    }

    if (error) {
        return <LemonBanner type="error">{error}</LemonBanner>
    }

    return <img src={src} onLoad={onImageLoad} />
}

export const NotebookNodeImage = createPostHogWidgetNode({
    nodeType: NotebookNodeType.Image,
    title: 'Image',
    Component,
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
