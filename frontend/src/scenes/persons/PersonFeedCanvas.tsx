import { useActions } from 'kea'
import { useEffect } from 'react'

import { PersonType } from '~/types'
import { notebookLogic, NotebookLogicProps } from 'scenes/notebooks/Notebook/notebookLogic'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'

type PersonFeedCanvasProps = {
    person: PersonType
}

const PersonFeedCanvas = ({ person }: PersonFeedCanvasProps): JSX.Element => {
    const id = person.id

    const logicProps: NotebookLogicProps = {
        shortId: `canvas-${id}`,
        mode: 'canvas',
    }

    const { setLocalContent } = useActions(notebookLogic(logicProps))

    useEffect(() => {
        const personId = person.distinct_ids[0]
        const canvas = {
            type: 'doc',
            content: [
                {
                    type: 'ph-person-feed',
                    attrs: {
                        height: null,
                        title: null,
                        nodeId: '6d485066-ec99-483d-8b98-4d8a2dc9cc4b',
                        id: personId,
                        __init: null,
                        children: [
                            {
                                type: 'ph-person',
                                attrs: { id: personId },
                            },
                            {
                                type: 'ph-map',
                                attrs: { id: personId },
                            },
                            {
                                type: 'ph-properties',
                                attrs: { id: personId },
                            },
                        ],
                    },
                },
            ],
        }

        setLocalContent(canvas)
    }, [person])

    return <Notebook {...logicProps} editable={false} />
}

export default PersonFeedCanvas
