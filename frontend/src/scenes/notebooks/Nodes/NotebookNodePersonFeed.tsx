import { useActions, useValues } from 'kea'

import { NotebookNodeType } from '~/types'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeProps } from '../Notebook/utils'
import { notebookNodePersonFeedLogic } from './notebookNodePersonFeedLogic'
import { useEffect } from 'react'

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodePersonFeedAttributes>): JSX.Element => {
    const { personId } = attributes
    // const personId = 'abc'
    const { sessionsTimeline } = useValues(notebookNodePersonFeedLogic({ personId }))
    const { loadSessionsTimeline } = useActions(notebookNodePersonFeedLogic({ personId }))

    // useEffect(() => {
    //     console.debug('sssssssssssss')
    //     loadSessionsTimeline()
    // }, [])

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
