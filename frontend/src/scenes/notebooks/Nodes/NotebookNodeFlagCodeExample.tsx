import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { useActions, useValues } from 'kea'
import { FeatureFlagLogicProps, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagCodeExample } from 'scenes/feature-flags/FeatureFlagCodeExample'
import { urls } from 'scenes/urls'
import { JSONContent, NotebookNodeProps } from '../Notebook/utils'
import { notebookNodeLogic } from './notebookNodeLogic'
import { useEffect } from 'react'
import { NotFound } from 'lib/components/NotFound'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeFlagCodeExampleAttributes>): JSX.Element => {
    const { id } = attributes
    const { featureFlag, featureFlagMissing } = useValues(featureFlagLogic({ id }))
    const { expanded } = useValues(notebookNodeLogic)
    const { setTitlePlaceholder } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder(
            featureFlag.key ? `Feature flag code example: ${featureFlag.key}` : 'Feature flag code example'
        )
    }, [featureFlag?.key])

    if (!featureFlagMissing) {
        return <NotFound object="feature flag" />
    }

    return <div className="p-2">{expanded && <FeatureFlagCodeExample featureFlag={featureFlag} />}</div>
}

type NotebookNodeFlagCodeExampleAttributes = {
    id: FeatureFlagLogicProps['id']
}

export const NotebookNodeFlagCodeExample = createPostHogWidgetNode<NotebookNodeFlagCodeExampleAttributes>({
    nodeType: NotebookNodeType.FeatureFlagCodeExample,
    titlePlaceholder: 'Feature flag code example',
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
