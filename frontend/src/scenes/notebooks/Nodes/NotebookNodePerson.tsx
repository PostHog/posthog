import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, PropertyDefinitionType } from '~/types'
import { useValues } from 'kea'
import { LemonDivider } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { posthogNodePasteRule } from './utils'
import { PersonDisplay } from '@posthog/apps-common'
import { personLogic } from 'scenes/persons/personLogic'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

const HEIGHT = 300

const Component = (props: NodeViewProps): JSX.Element => {
    const id = props.node.attrs.id
    const logic = personLogic({ id })

    const { person, personLoading } = useValues(logic)

    return (
        <NodeWrapper
            nodeType={NotebookNodeType.Person}
            title="Person"
            {...props}
            href={urls.person(id)}
            heightEstimate={HEIGHT}
            minHeight={100}
            resizeable={props.selected}
        >
            <div className="flex flex-col overflow-hidden">
                <div className="p-4 flex-0 font-semibold">
                    {personLoading ? (
                        <LemonSkeleton className="h-6" />
                    ) : (
                        <PersonDisplay withIcon person={person} noLink noPopover />
                    )}
                </div>

                {props.selected && (
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
        </NodeWrapper>
    )
}

export const NotebookNodePerson = Node.create({
    name: NotebookNodeType.Person,
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            height: {
                default: HEIGHT,
            },
            id: '',
        }
    },

    parseHTML() {
        return [
            {
                tag: NotebookNodeType.Person,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.Person, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },

    addPasteRules() {
        return [
            posthogNodePasteRule({
                find: urls.person('') + '(.+)',
                type: this.type,
                getAttributes: (match) => {
                    return { id: match[1] }
                },
            }),
        ]
    },
})
