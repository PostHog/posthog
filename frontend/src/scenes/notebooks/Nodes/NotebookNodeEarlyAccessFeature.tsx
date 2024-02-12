import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { EarlyAccessFeatureStage, EarlyAccessFeatureType, NotebookNodeType } from '~/types'
import { BindLogic, useActions, useValues } from 'kea'
import { IconFlag, IconRocketLaunch } from 'lib/lemon-ui/icons'
import { LemonDivider, LemonTag } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { JSONContent, NotebookNodeProps } from '../Notebook/utils'
import {
    EarlyAccessFeatureLogicProps,
    earlyAccessFeatureLogic,
} from 'scenes/early-access-features/earlyAccessFeatureLogic'
import { PersonList } from 'scenes/early-access-features/EarlyAccessFeature'
import { buildFlagContent } from './NotebookNodeFlag'
import { useEffect } from 'react'
import { NotFound } from 'lib/components/NotFound'

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
    }, [earlyAccessFeature])

    useEffect(() => {
        setTitlePlaceholder(
            earlyAccessFeature.name ? `Early Access Management: ${earlyAccessFeature.name}` : 'Early Access Management'
        )
    }, [earlyAccessFeature?.name])

    if (earlyAccessFeatureMissing) {
        return <NotFound object="early access feature" />
    }

    return (
        <div>
            <BindLogic logic={earlyAccessFeatureLogic} props={{ id }}>
                <div className="flex items-center gap-2 p-3">
                    <IconRocketLaunch className="text-lg" />
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
                                            <span className="text-muted">No description</span>
                                        )}
                                    </div>
                                </div>
                                <div className="mb-2">
                                    <b>Documentation URL</b>
                                    <div>
                                        {earlyAccessFeature.documentation_url ? (
                                            earlyAccessFeature.documentation_url
                                        ) : (
                                            <span className="text-muted">No documentation URL</span>
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
        find: urls.earlyAccessFeature('') + '(.+)',
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
