import { connect, kea, key, listeners, path, props, selectors } from 'kea'

import { JSONContent, RichContentNode } from 'lib/components/RichContentEditor/types'
import { FeatureFlagLogicProps, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { NotebookNodeType } from '../types'
import { buildEarlyAccessFeatureContent } from './NotebookNodeEarlyAccessFeature'
import type { notebookNodeFlagLogicType } from './NotebookNodeFlagLogicType'
import { buildSurveyContent } from './NotebookNodeSurvey'

export type NotebookNodeFlagLogicProps = {
    id: FeatureFlagLogicProps['id']
    insertAfter: (content: JSONContent) => void
}

export const notebookNodeFlagLogic = kea<notebookNodeFlagLogicType>([
    props({} as NotebookNodeFlagLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodeFlagLogic', key]),
    key(({ id }) => id),

    connect((props: NotebookNodeFlagLogicProps) => ({
        actions: [featureFlagLogic({ id: props.id }), ['createEarlyAccessFeatureSuccess', 'createSurveySuccess']],
        values: [featureFlagLogic({ id: props.id }), ['featureFlag', 'hasEarlyAccessFeatures', 'hasSurveys']],
    })),
    listeners(({ props }) => ({
        createEarlyAccessFeatureSuccess: async ({ newEarlyAccessFeature }) => {
            props.insertAfter(buildEarlyAccessFeatureContent(newEarlyAccessFeature.id))
        },
        createSurveySuccess: async ({ newSurvey }) => {
            props.insertAfter(buildSurveyContent(newSurvey.id))
        },
    })),
    selectors({
        shouldDisableInsertEarlyAccessFeature: [
            (s) => [s.featureFlag, s.hasEarlyAccessFeatures],
            (featureFlag, hasEarlyAccessFeatures) =>
                (nextNode: RichContentNode | null): boolean => {
                    return (
                        (nextNode?.type.name === NotebookNodeType.EarlyAccessFeature &&
                            hasEarlyAccessFeatures &&
                            featureFlag.features &&
                            nextNode?.attrs.id === featureFlag.features[0].id) ||
                        false
                    )
                },
        ],
        shouldDisableInsertSurvey: [
            (s) => [s.featureFlag, s.hasSurveys],
            (featureFlag, hasSurveys) =>
                (nextNode: RichContentNode | null): boolean => {
                    return (
                        (nextNode?.type.name === NotebookNodeType.Survey &&
                            hasSurveys &&
                            featureFlag.surveys &&
                            nextNode?.attrs.id === featureFlag.surveys[0].id) ||
                        false
                    )
                },
        ],
    }),
])
