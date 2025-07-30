import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { BindLogic, useActions, useValues } from 'kea'
import { featureFlagLogic, FeatureFlagLogicProps } from 'scenes/feature-flags/featureFlagLogic'
import { IconRecording, IconSurveys } from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { LemonDivider } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { buildPlaylistContent } from './NotebookNodePlaylist'
import { buildCodeExampleContent } from './NotebookNodeFlagCodeExample'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { buildEarlyAccessFeatureContent } from './NotebookNodeEarlyAccessFeature'
import { notebookNodeFlagLogic } from './NotebookNodeFlagLogic'
import { buildSurveyContent } from './NotebookNodeSurvey'
import { useEffect } from 'react'
import { NotFound } from 'lib/components/NotFound'
import { IconFlag, IconRocket } from '@posthog/icons'
import { INTEGER_REGEX_MATCH_GROUPS } from './utils'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { NotebookNodeProps, NotebookNodeType } from '../types'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeFlagAttributes>): JSX.Element => {
    const { id } = attributes
    const {
        featureFlag,
        featureFlagLoading,
        recordingFilterForFlag,
        featureFlagMissing,
        hasEarlyAccessFeatures,
        canCreateEarlyAccessFeature,
        hasSurveys,
    } = useValues(featureFlagLogic({ id }))
    const { createEarlyAccessFeature, createSurvey } = useActions(featureFlagLogic({ id }))
    const { expanded, nextNode } = useValues(notebookNodeLogic)
    const { insertAfter, setActions, setTitlePlaceholder } = useActions(notebookNodeLogic)

    const { shouldDisableInsertEarlyAccessFeature, shouldDisableInsertSurvey } = useValues(
        notebookNodeFlagLogic({ id, insertAfter })
    )

    useEffect(() => {
        setTitlePlaceholder(featureFlag.key ? `Feature flag: ${featureFlag.key}` : 'Feature flag')

        setActions([
            {
                icon: <IconSurveys />,
                text: `${hasSurveys ? 'View' : 'Create'} survey`,
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
                text: 'View Replays',
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
    }, [featureFlag])

    if (featureFlagMissing) {
        return <NotFound object="feature flag" />
    }

    return (
        <div>
            <BindLogic logic={featureFlagLogic} props={{ id }}>
                <div className="flex items-center gap-2 p-3">
                    <IconFlag className="text-lg" />
                    {featureFlagLoading ? (
                        <LemonSkeleton className="h-6 flex-1" />
                    ) : (
                        <>
                            <span className="flex-1 font-semibold truncate">{featureFlag.key}</span>
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

                {expanded ? (
                    <>
                        <LemonDivider className="my-0" />
                        <div className="p-2">
                            <FeatureFlagReleaseConditions readOnly filters={featureFlag.filters} />
                        </div>
                    </>
                ) : null}
            </BindLogic>
        </div>
    )
}

type NotebookNodeFlagAttributes = {
    id: FeatureFlagLogicProps['id']
}

export const NotebookNodeFlag = createPostHogWidgetNode<NotebookNodeFlagAttributes>({
    nodeType: NotebookNodeType.FeatureFlag,
    titlePlaceholder: 'Feature flag',
    Component,
    heightEstimate: '3rem',
    href: (attrs) => urls.featureFlag(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: urls.featureFlag(INTEGER_REGEX_MATCH_GROUPS),
        getAttributes: async (match) => {
            return { id: match[1] as FeatureFlagLogicProps['id'] }
        },
    },
})

export function buildFlagContent(id: FeatureFlagLogicProps['id']): JSONContent {
    return {
        type: NotebookNodeType.FeatureFlag,
        attrs: { id },
    }
}
