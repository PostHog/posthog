import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { useValues } from 'kea'
import { FeatureFlagLogicProps, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagCodeExample } from 'scenes/feature-flags/FeatureFlagCodeExample'
import { urls } from 'scenes/urls'
import { JSONContent, NotebookNodeViewProps } from '../Notebook/utils'
import { notebookNodeLogic } from './notebookNodeLogic'
import { useEffect } from 'react'

const Component = (props: NotebookNodeViewProps<NotebookNodeFlagCodeExampleAttributes>): JSX.Element => {
    const { id } = props.attributes
    const { featureFlag } = useValues(featureFlagLogic({ id }))
    const { expanded } = useValues(notebookNodeLogic)

    useEffect(() => {
        props.updateAttributes({
            title: featureFlag.key ? `Feature flag code example: ${featureFlag.key}` : 'Feature flag code example',
        })
    }, [featureFlag?.key])

    return <div className="p-2">{expanded && <FeatureFlagCodeExample featureFlag={featureFlag} />}</div>
}

type NotebookNodeFlagCodeExampleAttributes = {
    id: FeatureFlagLogicProps['id']
}

export const NotebookNodeFlagCodeExample = createPostHogWidgetNode<NotebookNodeFlagCodeExampleAttributes>({
    nodeType: NotebookNodeType.FeatureFlagCodeExample,
    defaultTitle: 'Feature flag code example',
    Component,
    heightEstimate: '3rem',
    startExpanded: true,
    href: (attrs) => urls.featureFlag(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
    },
})

export function buildCodeExampleContent(id: FeatureFlagLogicProps['id']): JSONContent {
    return {
        type: NotebookNodeType.FeatureFlagCodeExample,
        attrs: { id },
    }
}
