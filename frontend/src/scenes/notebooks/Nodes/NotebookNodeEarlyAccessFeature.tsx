import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconFlag, IconRocket } from '@posthog/icons'
import { LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { urls } from '~/scenes/urls'
import { EarlyAccessFeatureStage, EarlyAccessFeatureType } from '~/types'

import { PersonList } from 'products/early_access_features/frontend/EarlyAccessFeature'
import {
    EarlyAccessFeatureLogicProps,
    earlyAccessFeatureLogic,
} from 'products/early_access_features/frontend/earlyAccessFeatureLogic'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { buildFlagContent } from './NotebookNodeFlag'
import { notebookNodeLogic } from './notebookNodeLogic'
import { OPTIONAL_PROJECT_NON_CAPTURE_GROUP, UUID_REGEX_MATCH_GROUPS } from './utils'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeEarlyAccessAttributes>): JSX.Element => {
    const { id } = attributes
    const { earlyAccessFeature, earlyAccessFeatureLoading, earlyAccessFeatureMissing } = useValues(
        earlyAccessFeatureLogic({ id })
    )
    const { expanded } = useValues(notebookNodeLogic)
    const { insertAfter, setActions, setTitlePlaceholder } = useActions(notebookNodeLogic)

    useEffect(() => {
        const flagId = (earlyAccessFeature as EarlyAccessFeatureType).feature_flag?.id

        setActions(
            flagId
                ? [
                      {
                          text: 'View feature flag',
                          icon: <IconFlag />,
                          onClick: () => insertAfter(buildFlagContent(flagId)),
                      },
                  ]
                : []
        )
        // oxlint-disable-next-line exhaustive-deps
    }, [earlyAccessFeature])

    useEffect(() => {
        setTitlePlaceholder(
            earlyAccessFeature.name ? `Early Access Management: ${earlyAccessFeature.name}` : 'Early Access Management'
        )
        // oxlint-disable-next-line exhaustive-deps
    }, [earlyAccessFeature?.name])

    if (earlyAccessFeatureMissing) {
        return <NotFound object="early access feature" />
    }

    return (
        <div>
            <BindLogic logic={earlyAccessFeatureLogic} props={{ id }}>
                <div className="flex items-center gap-2 p-3">
                    <IconRocket className="text-lg" />
                    {earlyAccessFeatureLoading ? (
                        <LemonSkeleton className="h-6 flex-1" />
                    ) : (
                        <>
                            <span className="flex-1 font-semibold truncate">{earlyAccessFeature.name}</span>
                            <LemonTag
                                type={
                                    earlyAccessFeature.stage === EarlyAccessFeatureStage.Beta
                                        ? 'warning'
                                        : earlyAccessFeature.stage === EarlyAccessFeatureStage.GeneralAvailability
                                          ? 'success'
                                          : 'default'
                                }
                                className="uppercase"
                            >
                                {earlyAccessFeature.stage}
                            </LemonTag>
                        </>
                    )}
                </div>

                {expanded ? (
                    <>
                        <LemonDivider className="my-0" />
                        {earlyAccessFeature.stage === EarlyAccessFeatureStage.Beta ? (
                            <div className="p-2">
                                <PersonList earlyAccessFeature={earlyAccessFeature as EarlyAccessFeatureType} />
                            </div>
                        ) : (
                            <div className="p-2">
                                <div className="mb-2">
                                    <b>Description</b>
                                    <div>
                                        {earlyAccessFeature.description ? (
                                            earlyAccessFeature.description
                                        ) : (
                                            <span className="text-secondary">No description</span>
                                        )}
                                    </div>
                                </div>
                                <div className="mb-2">
                                    <b>Documentation URL</b>
                                    <div>
                                        {earlyAccessFeature.documentation_url ? (
                                            earlyAccessFeature.documentation_url
                                        ) : (
                                            <span className="text-secondary">No documentation URL</span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </>
                ) : null}
            </BindLogic>
        </div>
    )
}

type NotebookNodeEarlyAccessAttributes = {
    id: EarlyAccessFeatureLogicProps['id']
}

export const NotebookNodeEarlyAccessFeature = createPostHogWidgetNode<NotebookNodeEarlyAccessAttributes>({
    nodeType: NotebookNodeType.EarlyAccessFeature,
    titlePlaceholder: 'Early Access Management',
    Component,
    heightEstimate: '3rem',
    href: (attrs) => urls.earlyAccessFeature(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: OPTIONAL_PROJECT_NON_CAPTURE_GROUP + urls.earlyAccessFeature(UUID_REGEX_MATCH_GROUPS),
        getAttributes: async (match) => {
            return { id: match[1] }
        },
    },
})

export function buildEarlyAccessFeatureContent(id: EarlyAccessFeatureLogicProps['id']): JSONContent {
    return {
        type: NotebookNodeType.EarlyAccessFeature,
        attrs: { id },
    }
}
