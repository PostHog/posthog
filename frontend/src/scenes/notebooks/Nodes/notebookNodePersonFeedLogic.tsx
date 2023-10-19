import { connect, kea, key, listeners, path, props, selectors } from 'kea'
import { JSONContent, Node } from '../Notebook/utils'
import { FeatureFlagLogicProps, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { buildEarlyAccessFeatureContent } from './NotebookNodeEarlyAccessFeature'
import { NotebookNodeType } from '~/types'

import type { notebookNodeFlagLogicType } from './NotebookNodeFlagLogicType'
import { buildSurveyContent } from './NotebookNodeSurvey'

import type { notebookNodeFlagLogicType } from './notebookNodeFlagLogicType'

export type NotebookNodePersonFeedLogicProps = {
    personId: string
    // id: FeatureFlagLogicProps['id']
    // insertAfter: (content: JSONContent) => void
}

export const notebookNodePersonFeedLogic = kea([
    props({} as NotebookNodePersonFeedLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodePersonFeedLogic', key]),
    key(({ personId }) => personId),

    // connect((props: NotebookNodePersonFeedLogicProps) => ({
    //     actions: [featureFlagLogic({ id: props.id }), ['createEarlyAccessFeatureSuccess', 'createSurveySuccess']],
    //     values: [featureFlagLogic({ id: props.id }), ['featureFlag', 'hasEarlyAccessFeatures', 'hasSurveys']],
    // })),
    // listeners(({ props }) => ({
    //     createEarlyAccessFeatureSuccess: async ({ newEarlyAccessFeature }) => {
    //         props.insertAfter(buildEarlyAccessFeatureContent(newEarlyAccessFeature.id))
    //     },
    //     createSurveySuccess: async ({ newSurvey }) => {
    //         props.insertAfter(buildSurveyContent(newSurvey.id))
    //     },
    // })),
    // selectors({
    //     shouldDisableInsertEarlyAccessFeature: [
    //         (s) => [s.featureFlag, s.hasEarlyAccessFeatures],
    //         (featureFlag, hasEarlyAccessFeatures) =>
    //             (nextNode: Node | null): boolean => {
    //                 return (
    //                     (nextNode?.type.name === NotebookNodeType.EarlyAccessFeature &&
    //                         hasEarlyAccessFeatures &&
    //                         featureFlag.features &&
    //                         nextNode?.attrs.id === featureFlag.features[0].id) ||
    //                     false
    //                 )
    //             },
    //     ],
    //     shouldDisableInsertSurvey: [
    //         (s) => [s.featureFlag, s.hasSurveys],
    //         (featureFlag, hasSurveys) =>
    //             (nextNode: Node | null): boolean => {
    //                 return (
    //                     (nextNode?.type.name === NotebookNodeType.Survey &&
    //                         hasSurveys &&
    //                         featureFlag.surveys &&
    //                         nextNode?.attrs.id === featureFlag.surveys[0].id) ||
    //                     false
    //                 )
    //             },
    //     ],
    // }),
])
