import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconFlag, IconRocket } from '@posthog/icons'

import { NotFound } from 'lib/components/NotFound'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { IconRecording, IconSurveys } from 'lib/lemon-ui/icons'
import { FeatureFlagLogicProps, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import {
    FEATURE_FLAG_NOTEBOOK_WIDGET_VIEWS,
    FeatureFlagNotebookWidgetAttributes,
    withFeatureFlagNotebookMetadata,
} from 'scenes/feature-flags/featureFlagNotebookWidgetViews'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { urls } from 'scenes/urls'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { buildEarlyAccessFeatureContent } from './NotebookNodeEarlyAccessFeature'
import { buildCodeExampleContent } from './NotebookNodeFlagCodeExample'
import { notebookNodeFlagLogic } from './NotebookNodeFlagLogic'
import { notebookNodeLogic } from './notebookNodeLogic'
import { buildPlaylistContent } from './NotebookNodePlaylist'
import { buildSurveyContent } from './NotebookNodeSurvey'

function FeatureFlagNotebookActions({ attributes }: NotebookNodeProps<FeatureFlagNotebookWidgetAttributes>): null {
    const { id } = attributes
    const {
        featureFlag,
        recordingFilterForFlag,
        hasEarlyAccessFeatures,
        canCreateEarlyAccessFeature,
        hasSurveys,
        newEarlyAccessFeatureLoading,
        newSurveyLoading,
    } = useValues(featureFlagLogic({ id }))
    const { createEarlyAccessFeature, createSurvey } = useActions(featureFlagLogic({ id }))
    const { nextNode } = useValues(notebookNodeLogic)
    const { insertAfter, setActions } = useActions(notebookNodeLogic)

    const { shouldDisableInsertEarlyAccessFeature, shouldDisableInsertSurvey } = useValues(
        notebookNodeFlagLogic({ id, insertAfter })
    )

    useEffect(() => {
        setActions([
            {
                icon: <IconSurveys />,
                text: `${hasSurveys ? 'View' : 'Create'} survey`,
                disabledReason: !hasSurveys && newSurveyLoading ? 'Creating survey' : undefined,
                onClick: () => {
                    if (!hasSurveys) {
                        return createSurvey()
                    }
                    if ((featureFlag?.surveys?.length || 0) <= 0) {
                        return
                    }
                    if (!shouldDisableInsertSurvey(nextNode) && featureFlag.surveys) {
                        insertAfter(buildSurveyContent(featureFlag.surveys[0].id))
                    }
                },
            },
            {
                icon: <IconFlag />,
                text: 'Show implementation',
                onClick: () => {
                    if (nextNode?.type.name !== NotebookNodeType.FeatureFlagCodeExample) {
                        insertAfter(buildCodeExampleContent(id))
                    }
                },
            },
            {
                icon: <IconRecording />,
                text: 'View replays',
                onClick: () => {
                    if (nextNode?.type.name !== NotebookNodeType.RecordingPlaylist) {
                        insertAfter(buildPlaylistContent(recordingFilterForFlag))
                    }
                },
            },
            canCreateEarlyAccessFeature
                ? {
                      text: `${hasEarlyAccessFeatures ? 'View' : 'Create'} early access feature`,
                      icon: <IconRocket />,
                      disabledReason:
                          !hasEarlyAccessFeatures && newEarlyAccessFeatureLoading
                              ? 'Creating early access feature'
                              : undefined,
                      onClick: () => {
                          if (!hasEarlyAccessFeatures) {
                              createEarlyAccessFeature()
                          } else {
                              if ((featureFlag?.features?.length || 0) <= 0) {
                                  return
                              }
                              if (!shouldDisableInsertEarlyAccessFeature(nextNode) && featureFlag.features) {
                                  insertAfter(buildEarlyAccessFeatureContent(featureFlag.features[0].id))
                              }
                          }
                      },
                  }
                : undefined,
        ])
        // oxlint-disable-next-line exhaustive-deps
    }, [featureFlag, newEarlyAccessFeatureLoading, newSurveyLoading])

    return null
}

const Component = ({ attributes }: NotebookNodeProps<FeatureFlagNotebookWidgetAttributes>): JSX.Element => {
    const { id } = attributes
    const { featureFlag, featureFlagMissing } = useValues(featureFlagLogic({ id }))
    const { expanded } = useValues(notebookNodeLogic)

    if (featureFlagMissing) {
        return <NotFound object="feature flag" />
    }

    return (
        <>
            <BindLogic logic={featureFlagLogic} props={{ id }}>
                {expanded ? (
                    <div className="p-2">
                        <FeatureFlagReleaseConditions readOnly filters={featureFlag.filters} />
                    </div>
                ) : null}
            </BindLogic>
        </>
    )
}

export const NotebookNodeFlag = createPostHogWidgetNode<FeatureFlagNotebookWidgetAttributes>({
    nodeType: NotebookNodeType.FeatureFlag,
    titlePlaceholder: 'Feature flag',
    editableTitle: false,
    Component: withFeatureFlagNotebookMetadata(Component),
    ToolbarComponent: FeatureFlagNotebookActions,
    heightEstimate: '3rem',
    href: (attrs) => urls.featureFlag(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
        view: {},
    },
    defaultView: getNotebookWidgetDefaultView('FeatureFlag'),
    views: FEATURE_FLAG_NOTEBOOK_WIDGET_VIEWS,
})

export function buildFlagContent(id: FeatureFlagLogicProps['id']): JSONContent {
    return {
        type: NotebookNodeType.FeatureFlag,
        attrs: { id },
    }
}
