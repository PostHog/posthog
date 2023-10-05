import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, PropertyDefinitionType } from '~/types'
import { useValues } from 'kea'
import { LemonDivider } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { PersonDisplay, TZLabel } from '@posthog/apps-common'
import { personLogic } from 'scenes/persons/personLogic'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeViewProps } from '../Notebook/utils'
import { asDisplay } from 'scenes/persons/person-utils'
import { useEffect } from 'react'

const Component = (props: NotebookNodeViewProps<NotebookNodePersonAttributes>): JSX.Element => {
    const { id } = props.attributes

    const logic = personLogic({ id })
    const { person, personLoading } = useValues(logic)
    const { expanded } = useValues(notebookNodeLogic)
    // const { setActions, insertAfter } = useActions(notebookNodeLogic)

    const title = person ? `Person: ${asDisplay(person)}` : 'Person'

    useEffect(() => {
        setTimeout(() => {
            props.updateAttributes({ title })
        }, 0)
    }, [title])

    // useEffect(() => {
    //     setActions([
    //         {
    //             text: "Events",
    //             onClick: () => {
    //                 insertAfter({
    //                     type: NotebookNodeType.Events,
    //                 })
    //         }
    //     ])
    // }, [person])

    useEffect(() => {
        props.updateAttributes({
            title: person ? `Person: ${asDisplay(person)}` : 'Person',
        })
    }, [person])

    return (
        <div className="flex flex-col overflow-hidden">
            <div className="p-4 flex-0 flex gap-2 justify-between">
                {personLoading ? (
                    <LemonSkeleton className="h-6" />
                ) : (
                    <>
                        <span className="font-semibold">
                            <PersonDisplay withIcon person={person} noLink noPopover />
                        </span>

                        {person ? (
                            <div>
                                <span className="text-muted">First seen:</span>{' '}
                                {person.created_at ? <TZLabel time={person.created_at} /> : 'unknown'}
                            </div>
                        ) : null}
                    </>
                )}
            </div>

            {expanded && (
                <>
                    <LemonDivider className="my-0 mx-2" />
                    <div className="flex-1 p-2 overflow-y-auto">
                        <PropertiesTable
                            type={PropertyDefinitionType.Person}
                            properties={person?.properties}
                            filterable
                            searchable
                        />
                    </div>
                </>
            )}
        </div>
    )
}

type NotebookNodePersonAttributes = {
    id: string
}

export const NotebookNodePerson = createPostHogWidgetNode<NotebookNodePersonAttributes>({
    nodeType: NotebookNodeType.Person,
    defaultTitle: 'Person',
    Component,
    heightEstimate: 300,
    minHeight: 100,
    href: (attrs) => urls.personByDistinctId(attrs.id),
    resizeable: true,
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: urls.personByDistinctId('(.+)', false),
        getAttributes: async (match) => {
            return { id: match[1] }
        },
    },
    serializedText: (attrs) => {
        const personTitle = attrs?.title || ''
        const personId = attrs?.id || ''
        return `${personTitle} ${personId}`.trim()
    },
})
