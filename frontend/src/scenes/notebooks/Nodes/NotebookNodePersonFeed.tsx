import { useValues } from 'kea'

import { NotebookNodeType } from '~/types'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeProps } from '../Notebook/utils'
import { notebookNodePersonFeedLogic } from './notebookNodePersonFeedLogic'

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodePersonFeedAttributes>): JSX.Element => {
    const { personId } = attributes
    // const personId = 'abc'
    const {} = useValues(notebookNodePersonFeedLogic({ personId }))

    return <pre></pre>
}

type NotebookNodePersonFeedAttributes = {
    personId: string
}

export const NotebookNodePersonFeed = createPostHogWidgetNode<NotebookNodePersonFeedAttributes>({
    nodeType: NotebookNodeType.PersonFeed,
    titlePlaceholder: 'Feed',
    Component,
    resizeable: false,
    expandable: false,
    attributes: {
        personId: {},
    },
})
