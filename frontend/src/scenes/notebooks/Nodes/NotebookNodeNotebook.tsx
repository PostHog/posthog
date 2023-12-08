import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, NotebookType } from '~/types'
import { urls } from 'scenes/urls'
import { NotebookNodeProps } from '../Notebook/utils'
import { Notebook } from '../Notebook/Notebook'
import { notebookLogic } from '../Notebook/notebookLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeNotebookAttributes>): JSX.Element => {
    const { id } = attributes

    // TODO: This is far from perfect as it will get mounted by the child so we need to somehow account for that...
    const mountedLogic = notebookLogic.findMounted({ shortId: id })

    if (mountedLogic) {
        return (
            <div className="border border-dashed rounded p-4 m-4 text-center text-muted-alt italic">
                Notebook not displayed as it is embedded in itself
            </div>
        )
    }

    return (
        <div className="px-4">
            <Notebook shortId={id} editable={false} />
        </div>
    )
}

type NotebookNodeNotebookAttributes = {
    id: NotebookType['short_id']
}

export const NotebookNodeNotebook = createPostHogWidgetNode<NotebookNodeNotebookAttributes>({
    nodeType: NotebookNodeType.Notebook,
    titlePlaceholder: 'Embedded notebook',
    Component,
    heightEstimate: '10rem',
    href: (attrs) => urls.notebook(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: urls.notebook('') + '(.+)',
        getAttributes: async (match) => {
            return { id: match[1] }
        },
    },
})
