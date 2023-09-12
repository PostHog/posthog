import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { EarlyAccessFeatureStage, EarlyAccessFeatureType, NotebookNodeType } from '~/types'
import { BindLogic, useActions, useValues } from 'kea'
import { IconFlag, IconRocketLaunch } from 'lib/lemon-ui/icons'
import { LemonButton, LemonDivider, LemonTag } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { JSONContent, NotebookNodeViewProps } from '../Notebook/utils'
import api from 'lib/api'
import {
    EarlyAccessFeatureLogicProps,
    earlyAccessFeatureLogic,
} from 'scenes/early-access-features/earlyAccessFeatureLogic'
import { PersonList } from 'scenes/early-access-features/EarlyAccessFeature'
import { buildFlagContent } from './NotebookNodeFlag'

const Component = (props: NotebookNodeViewProps<NotebookNodeEarlyAccessAttributes>): JSX.Element => {
    const { id } = props.attributes
    const { earlyAccessFeature, earlyAccessFeatureLoading } = useValues(earlyAccessFeatureLogic({ id }))
    const { expanded } = useValues(notebookNodeLogic)
    const { insertAfter } = useActions(notebookNodeLogic)

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
                                    <b>Documentation Url</b>
                                    <div>
                                        {earlyAccessFeature.documentation_url ? (
                                            earlyAccessFeature.documentation_url
                                        ) : (
                                            <span className="text-muted">No documentation url</span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </>
                ) : null}

                <LemonDivider className="my-0" />
                <div className="p-2 mr-1 flex justify-end gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconFlag />}
                        onClick={() => {
                            insertAfter(
                                buildFlagContent(
                                    (earlyAccessFeature as EarlyAccessFeatureType).feature_flag?.id || 'new'
                                )
                            )
                        }}
                    >
                        View Feature Flag
                    </LemonButton>
                </div>
            </BindLogic>
        </div>
    )
}

type NotebookNodeEarlyAccessAttributes = {
    id: EarlyAccessFeatureLogicProps['id']
}

export const NotebookNodeEarlyAccessFeature = createPostHogWidgetNode<NotebookNodeEarlyAccessAttributes>({
    nodeType: NotebookNodeType.EarlyAccessFeature,
    title: async (attributes) => {
        const mountedEarlyAccessFeatureLogic = earlyAccessFeatureLogic.findMounted({ id: attributes.id })
        let title = mountedEarlyAccessFeatureLogic?.values.earlyAccessFeature.name || null
        if (title === null) {
            const retrievedEarlyAccessFeature: EarlyAccessFeatureType = await api.earlyAccessFeatures.get(attributes.id)
            if (retrievedEarlyAccessFeature) {
                title = retrievedEarlyAccessFeature.name
            }
        }

        return title ? `Early Access Management: ${title}` : 'Early Access Management'
    },
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
            return { id: match[1] as EarlyAccessFeatureLogicProps['id'] }
        },
    },
})

export function buildEarlyAccessFeatureContent(id: EarlyAccessFeatureLogicProps['id']): JSONContent {
    return {
        type: NotebookNodeType.EarlyAccessFeature,
        attrs: { id },
    }
}
