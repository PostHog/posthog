import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, PropertyDefinitionType } from '~/types'
import { useValues } from 'kea'
import { LemonDivider } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { posthogNodePasteRule } from './utils'
import { PersonHeader } from '@posthog/apps-common'
import { personLogic } from 'scenes/persons/personLogic'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

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
            resizeable={false}
        >
            <div className="border bg-bg-light rounded">
                <div className="p-4">
                    {personLoading ? (
                        <LemonSkeleton className="h-6" />
                    ) : (
                        <PersonHeader withIcon person={person} noLink />
                    )}
                </div>

                {props.selected && (
                    <>
                        <LemonDivider className="my-0" />
                        <div className="p-2 max-h-100 overflow-y-auto">
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
                editor: this.editor,
                getAttributes: async (match) => {
                    return { id: match[1] }
                },
            }),
        ]
    },
})
