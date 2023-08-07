import { api } from '@posthog/apps-common'
import { NodeViewProps } from '@tiptap/core'
import { lazyImageBlobReducer } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useEffect, useState } from 'react'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { MediaUploadResponse, NotebookNodeType } from '~/types'

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
    const { file, src } = props.node.attrs

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

    if (uploading) {
        return (
            <div>
                <Spinner />
            </div>
        )
    }

    return <img src={src} />
}

export const NotebookNodeImage = createPostHogWidgetNode({
    nodeType: NotebookNodeType.Image,
    title: 'Image',
    startExpanded: true,
    Component,
    heightEstimate: '3rem',
    resizeable: true,
    attributes: {
        file: {},
    },
})
