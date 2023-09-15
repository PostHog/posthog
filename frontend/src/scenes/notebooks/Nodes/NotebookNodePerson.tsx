import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, PropertyDefinitionType } from '~/types'
import { useValues } from 'kea'
import { LemonDivider } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { PersonDisplay } from '@posthog/apps-common'
import { personLogic } from 'scenes/persons/personLogic'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeViewProps } from '../Notebook/utils'
import { asDisplay } from 'scenes/persons/person-utils'
import api from 'lib/api'

const Component = (props: NotebookNodeViewProps<NotebookNodePersonAttributes>): JSX.Element => {
    const { id } = props.attributes
    const logic = personLogic({ id })
    const { person, personLoading } = useValues(logic)
    const { expanded } = useValues(notebookNodeLogic)

    return (
        <div className="flex flex-col overflow-hidden">
            <div className="p-4 flex-0 font-semibold">
                {personLoading ? (
                    <LemonSkeleton className="h-6" />
                ) : (
                    <PersonDisplay withIcon person={person} noLink noPopover />
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
    title: async (attributes) => {
        const theMountedPersonLogic = personLogic.findMounted({ id: attributes.id })
        let person = theMountedPersonLogic?.values.person || null

        if (person === null) {
            const response = await api.persons.list({ distinct_id: attributes.id })
            person = response.results[0]
        }

        return person ? `Person: ${asDisplay(person)}` : 'Person'
    },
    Component,
    heightEstimate: 300,
    minHeight: 100,
    href: (attrs) => urls.person(attrs.id),
    resizeable: true,
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: urls.person('(.+)'),
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
