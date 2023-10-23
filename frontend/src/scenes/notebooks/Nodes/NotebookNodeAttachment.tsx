import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { NotebookNodeProps } from '../Notebook/utils'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeAttachmentAttributes>): JSX.Element => {
    const { mediaLocation } = attributes

    return <video style={{ height: 400 }} controls src={mediaLocation} />
}

type NotebookNodeAttachmentAttributes = {
    mediaLocation: string
}

export const NotebookNodeAttachment = createPostHogWidgetNode<NotebookNodeAttachmentAttributes>({
    nodeType: NotebookNodeType.Attachment,
    titlePlaceholder: 'Attachment',
    Component,
    heightEstimate: 400,
    resizeable: false,
    expandable: false,
    autoHideMetadata: true,
    attributes: {
        mediaLocation: {},
    },
})
