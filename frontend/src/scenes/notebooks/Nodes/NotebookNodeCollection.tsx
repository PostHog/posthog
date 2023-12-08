import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { JSONContent, NotebookNodeProps } from '../Notebook/utils'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeCollectionAttributes>): JSX.Element => {
    const { id } = attributes

    return <div className="flex flex-col overflow-hidden">coming soon</div>
}

type NotebookNodeCollectionAttributes = {
    items: JSONContent[]
}

export const NotebookNodeCollection = createPostHogWidgetNode<NotebookNodeCollectionAttributes>({
    nodeType: NotebookNodeType.Collection,
    titlePlaceholder: 'Collection',
    Component,
    serializedText: () => {
        // TODO file is null when this runs... should it be?
        return ''
    },
    heightEstimate: 400,
    minHeight: 100,
    resizeable: true,
    expandable: false,
    autoHideMetadata: true,
    attributes: {
        items: {},
    },
})

export function buildNodeCollection(): JSONContent {
    return {
        type: NotebookNodeType.Collection,
        attrs: {
            items: [],
        },
    }
}
