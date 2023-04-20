import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'
import { useValues } from 'kea'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { IconFlag } from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { LemonDivider } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'

const Component = (props: NodeViewProps): JSX.Element => {
    const id = props.node.attrs.flag
    const logic = featureFlagLogic({ id })

    const { featureFlag } = useValues(logic)

    const previewContent = (
        <div className="p-4 flex items-center gap-2 justify-between">
            <IconFlag className="text-lg" />
            <span className="text-lg flex-1">{featureFlag.name}</span>

            <span className={clsx('text-white p-2 rounded', featureFlag.active ? 'bg-success' : 'bg-muted-alt')}>
                {featureFlag.active ? 'Enabled' : 'Disabled'}
            </span>
        </div>
    )

    console.log({ id })

    return (
        <NodeWrapper
            className={NotebookNodeType.FeatureFlag}
            title="FeatureFlag"
            {...props}
            preview={previewContent}
            href={urls.featureFlag(id)}
        >
            {previewContent}
            <LemonDivider />
            <p>More info here!</p>
        </NodeWrapper>
    )
}

export const FeatureFlagNode = Node.create({
    name: NotebookNodeType.FeatureFlag,
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            flag: {},
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
})
