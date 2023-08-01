import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { useValues } from 'kea'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { IconFlag, IconRecording } from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { posthogNodePasteRule } from './utils'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

const Component = (props: NodeViewProps): JSX.Element => {
    const { id } = props.node.attrs
    const logic = featureFlagLogic({ id })
    const { featureFlag, featureFlagLoading } = useValues(logic)

    return (
        <NodeWrapper
            nodeType={NotebookNodeType.FeatureFlag}
            title="Feature Flag"
            {...props}
            href={urls.featureFlag(id)}
            heightEstimate={'3rem'}
            resizeable={false}
        >
            <div>
                <div className="flex items-center gap-2 p-4">
                    <IconFlag className="text-lg" />
                    {featureFlagLoading ? (
                        <LemonSkeleton className="h-6 flex-1" />
                    ) : (
                        <>
                            <span className="flex-1 font-semibold truncate">{featureFlag.name}</span>
                            <span
                                className={clsx(
                                    'text-white rounded px-1',
                                    featureFlag.active ? 'bg-success' : 'bg-muted-alt'
                                )}
                            >
                                {featureFlag.active ? 'Enabled' : 'Disabled'}
                            </span>
                        </>
                    )}
                </div>

                {props.selected ? (
                    <>
                        <LemonDivider className="my-0" />
                        <div className="p-2">
                            <p>More info here!</p>
                        </div>
                        <LemonDivider className="my-0" />
                        <div className="p-2 flex justify-end">
                            <LemonButton type="secondary" size="small" icon={<IconRecording />}>
                                View Replays
                            </LemonButton>
                        </div>
                    </>
                ) : null}
            </div>
        </NodeWrapper>
    )
}

export const NotebookNodeFlag = Node.create({
    name: NotebookNodeType.FeatureFlag,
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            id: {},
        }
    },

    parseHTML() {
        return [
            {
                tag: NotebookNodeType.FeatureFlag,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.FeatureFlag, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },

    addPasteRules() {
        return [
            posthogNodePasteRule({
                find: urls.featureFlag('') + '(.+)',
                type: this.type,
                getAttributes: (match) => {
                    return { id: match[1] }
                },
            }),
        ]
    },
})
