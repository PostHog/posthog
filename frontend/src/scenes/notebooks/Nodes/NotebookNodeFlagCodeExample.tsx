import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { useValues } from 'kea'
import { FeatureFlagLogicProps, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagCodeExample } from 'scenes/feature-flags/FeatureFlagCodeExample'
import { urls } from 'scenes/urls'
import { JSONContent, NotebookNodeViewProps } from '../Notebook/utils'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = (props: NotebookNodeViewProps<NotebookNodeFlagCodeExampleAttributes>): JSX.Element => {
    const { id } = props.node.attrs
    const { featureFlag } = useValues(featureFlagLogic({ id }))
    const { expanded } = useValues(notebookNodeLogic)

    return <div className="p-2">{expanded && <FeatureFlagCodeExample featureFlag={featureFlag} />}</div>
}

type NotebookNodeFlagCodeExampleAttributes = {
    id: FeatureFlagLogicProps['id']
    expandedOnLoad?: boolean
}

export const NotebookNodeFlagCodeExample = createPostHogWidgetNode<NotebookNodeFlagCodeExampleAttributes>({
    nodeType: NotebookNodeType.FeatureFlagCodeExample,
    title: 'Feature Flag Code Example',
    Component,
    heightEstimate: '3rem',
    href: (attrs) => urls.featureFlag(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
        expandedOnLoad: {},
    },
    pasteOptions: {
        find: urls.featureFlag('') + '(.+)',
        getAttributes: async (match) => {
            return { id: match[1] as FeatureFlagLogicProps['id'] }
        },
    },
})

export function buildCodeExampleContent(id: FeatureFlagLogicProps['id'], expanded?: boolean): JSONContent {
    return {
        type: NotebookNodeType.FeatureFlagCodeExample,
        attrs: { id, expandedOnLoad: expanded },
    }
}
