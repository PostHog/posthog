import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconFlag } from '@posthog/icons'

import { getExperimentStatus } from 'scenes/experiments/experimentStatus'

import { experimentLogic } from '~/scenes/experiments/experimentLogic'
import { NotebookExperimentComponent } from '~/scenes/experiments/notebook'
import {
    EXPERIMENT_NOTEBOOK_WIDGET_VIEWS,
    ExperimentNotebookWidgetAttributes,
} from '~/scenes/experiments/notebook/experimentNotebookWidgetViews'
import { createPostHogWidgetNode } from '~/scenes/notebooks/Nodes/NodeWrapper'
import { getNotebookWidgetDefaultView } from '~/scenes/notebooks/notebookWidgetCatalog'
import { type NotebookNodeProps, NotebookNodeType } from '~/scenes/notebooks/types'
import { urls } from '~/scenes/urls'

import {
    getExperimentStatusColor,
    getExperimentStatusLabel,
} from 'products/experiments/frontend/scenes/experimentsLogic'

import { buildFlagContent } from './NotebookNodeFlag'
import { notebookNodeLogic } from './notebookNodeLogic'

function ExperimentNotebookToolbar({ attributes }: NotebookNodeProps<ExperimentNotebookWidgetAttributes>): null {
    const { experiment } = useValues(experimentLogic({ experimentId: attributes.id }))
    const { nextNode } = useValues(notebookNodeLogic)
    const { insertAfter, setActions, setTitlePlaceholder, setTitleStatus } = useActions(notebookNodeLogic)
    const featureFlagId = experiment?.feature_flag?.id

    useEffect(() => {
        setTitlePlaceholder(experiment?.name || 'Experiment')
        const status = experiment ? getExperimentStatus(experiment) : null
        setTitleStatus(
            status
                ? {
                      label: getExperimentStatusLabel(status),
                      type: getExperimentStatusColor(status),
                  }
                : null
        )
        setActions(
            featureFlagId
                ? [
                      {
                          text: 'View feature flag',
                          icon: <IconFlag />,
                          onClick: () => {
                              if (nextNode?.type.name !== NotebookNodeType.FeatureFlag) {
                                  insertAfter(buildFlagContent(featureFlagId))
                              }
                          },
                      },
                  ]
                : []
        )
    }, [experiment, featureFlagId, insertAfter, nextNode?.type.name, setActions, setTitlePlaceholder, setTitleStatus])

    return null
}

const Component = ({ attributes }: NotebookNodeProps<ExperimentNotebookWidgetAttributes>): JSX.Element => {
    const { id } = attributes
    const { expanded } = useValues(notebookNodeLogic)

    return <NotebookExperimentComponent id={id} expanded={expanded} />
}

export const NotebookNodeExperiment = createPostHogWidgetNode<ExperimentNotebookWidgetAttributes>({
    nodeType: NotebookNodeType.Experiment,
    titlePlaceholder: 'Experiment',
    editableTitle: false,
    Component,
    ToolbarComponent: ExperimentNotebookToolbar,
    heightEstimate: '3rem',
    href: (attrs) => urls.experiment(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
        view: {},
    },
    defaultView: getNotebookWidgetDefaultView('Experiment'),
    views: EXPERIMENT_NOTEBOOK_WIDGET_VIEWS,
})
