import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { FeatureFlagType, NotebookNodeType } from '~/types'
import { useValues } from 'kea'
import { FeatureFlagLogicProps, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagCodeExample } from 'scenes/feature-flags/FeatureFlagCodeExample'
import { urls } from 'scenes/urls'
import { JSONContent, NotebookNodeViewProps } from '../Notebook/utils'
import { notebookNodeLogic } from './notebookNodeLogic'
import api from 'lib/api'

const Component = (props: NotebookNodeViewProps<NotebookNodeFlagCodeExampleAttributes>): JSX.Element => {
    const { id } = props.attributes
    const { featureFlag } = useValues(featureFlagLogic({ id }))
    const { expanded } = useValues(notebookNodeLogic)

    return <div className="p-2">{expanded && <FeatureFlagCodeExample featureFlag={featureFlag} />}</div>
}

type NotebookNodeFlagCodeExampleAttributes = {
    id: FeatureFlagLogicProps['id']
}

export const NotebookNodeFlagCodeExample = createPostHogWidgetNode<NotebookNodeFlagCodeExampleAttributes>({
    nodeType: NotebookNodeType.FeatureFlagCodeExample,
    title: async (attributes) => {
        const mountedFlagLogic = featureFlagLogic.findMounted({ id: attributes.id })
        let title = mountedFlagLogic?.values.featureFlag.key || null

        if (title === null) {
            const retrievedFlag: FeatureFlagType = await api.featureFlags.get(Number(attributes.id))
            if (retrievedFlag) {
                title = retrievedFlag.key
            }
        }

        return title ? `Feature flag code example: ${title}` : 'Feature flag code example'
    },
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
