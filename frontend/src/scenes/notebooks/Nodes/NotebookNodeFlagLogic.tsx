import { connect, kea, key, listeners, path, props, selectors } from 'kea'
import { JSONContent, Node } from '../Notebook/utils'
import { FeatureFlagLogicProps, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { buildEarlyAccessFeatureContent } from './NotebookNodeEarlyAccessFeature'
import { NotebookNodeType } from '~/types'

import type { notebookNodeFlagLogicType } from './NotebookNodeFlagLogicType'

export type NotebookNodeFlagLogicProps = {
    id: FeatureFlagLogicProps['id']
    insertAfter: (content: JSONContent) => void
}

export const notebookNodeFlagLogic = kea<notebookNodeFlagLogicType>([
    props({} as NotebookNodeFlagLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodeFlagLogic', key]),
    key(({ id }) => id),

    connect((props: NotebookNodeFlagLogicProps) => ({
        actions: [featureFlagLogic({ id: props.id }), ['createEarlyAccessFeatureSuccess']],
        values: [featureFlagLogic({ id: props.id }), ['featureFlag', 'hasEarlyAccessFeatures']],
    })),
    listeners(({ props }) => ({
        createEarlyAccessFeatureSuccess: async ({ newEarlyAccessFeature }) => {
            props.insertAfter(buildEarlyAccessFeatureContent(newEarlyAccessFeature.id))
        },
    })),
    selectors({
        shouldDisableInsertEarlyAccessFeature: [
            (s) => [s.featureFlag, s.hasEarlyAccessFeatures],
            (featureFlag, hasEarlyAccessFeatures) =>
                (nextNode: Node | null): boolean => {
                    return (
                        (nextNode?.type.name === NotebookNodeType.EarlyAccessFeature &&
                            hasEarlyAccessFeatures &&
                            featureFlag.features &&
                            nextNode?.attrs.id === featureFlag.features[0].id) ||
                        false
                    )
                },
        ],
    }),
])
