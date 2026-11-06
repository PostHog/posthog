import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconFlag } from '@posthog/icons'

import { NotFound } from 'lib/components/NotFound'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { urls } from '~/scenes/urls'
import { EarlyAccessFeatureStage, EarlyAccessFeatureType } from '~/types'

import { PersonList } from 'products/early_access_features/frontend/EarlyAccessFeature'
import {
    EarlyAccessFeatureLogicProps,
    earlyAccessFeatureLogic,
} from 'products/early_access_features/frontend/earlyAccessFeatureLogic'
import {
    EARLY_ACCESS_FEATURE_NOTEBOOK_WIDGET_VIEWS,
    EarlyAccessFeatureNotebookWidgetAttributes,
    getEarlyAccessFeatureStageLabel,
    getEarlyAccessFeatureStageTagType,
} from 'products/early_access_features/frontend/earlyAccessFeatureNotebookWidgetViews'

import { getNotebookWidgetDefaultView } from '../notebookWidgetCatalog'
import { NotebookNodeProps, NotebookNodeType } from '../types'
import { buildFlagContent } from './NotebookNodeFlag'
import { notebookNodeLogic } from './notebookNodeLogic'

function EarlyAccessFeatureNotebookToolbar({
    attributes,
}: NotebookNodeProps<EarlyAccessFeatureNotebookWidgetAttributes>): null {
    const { id } = attributes
    const { earlyAccessFeature } = useValues(earlyAccessFeatureLogic({ id }))
    const { insertAfter, setActions, setTitlePlaceholder, setTitleStatus } = useActions(notebookNodeLogic)

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
        setTitlePlaceholder(earlyAccessFeature.name || 'Early access feature')
        setTitleStatus(
            earlyAccessFeature.stage
                ? {
                      label: getEarlyAccessFeatureStageLabel(earlyAccessFeature.stage),
                      type: getEarlyAccessFeatureStageTagType(earlyAccessFeature.stage),
                  }
                : null
        )
        // oxlint-disable-next-line exhaustive-deps
    }, [earlyAccessFeature?.name, earlyAccessFeature?.stage])

    return null
}

const Component = ({ attributes }: NotebookNodeProps<EarlyAccessFeatureNotebookWidgetAttributes>): JSX.Element => {
    const { id } = attributes
    const { earlyAccessFeature, earlyAccessFeatureMissing } = useValues(earlyAccessFeatureLogic({ id }))
    const { expanded } = useValues(notebookNodeLogic)

    if (earlyAccessFeatureMissing) {
        return <NotFound object="early access feature" />
    }

    return (
        <div>
            <BindLogic logic={earlyAccessFeatureLogic} props={{ id }}>
                {expanded ? (
                    <>
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

export const NotebookNodeEarlyAccessFeature = createPostHogWidgetNode<EarlyAccessFeatureNotebookWidgetAttributes>({
    nodeType: NotebookNodeType.EarlyAccessFeature,
    titlePlaceholder: 'Early access feature',
    editableTitle: false,
    Component,
    ToolbarComponent: EarlyAccessFeatureNotebookToolbar,
    heightEstimate: '3rem',
    href: (attrs) => urls.earlyAccessFeature(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
        view: {},
    },
    defaultView: getNotebookWidgetDefaultView('EarlyAccessFeature'),
    views: EARLY_ACCESS_FEATURE_NOTEBOOK_WIDGET_VIEWS,
})

export function buildEarlyAccessFeatureContent(id: EarlyAccessFeatureLogicProps['id']): JSONContent {
    return {
        type: NotebookNodeType.EarlyAccessFeature,
        attrs: { id },
    }
}
