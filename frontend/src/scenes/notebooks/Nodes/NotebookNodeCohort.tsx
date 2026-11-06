import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconPerson, IconTrends } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { COHORT_NOTEBOOK_WIDGET_VIEWS, CohortNotebookWidgetAttributes } from 'scenes/cohorts/cohortNotebookWidgetViews'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType } from '~/types'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'

function CohortNotebookToolbar({ attributes }: NotebookNodeProps<CohortNotebookWidgetAttributes>): null {
    const { id } = attributes
    const { cohort, cohortMissing } = useValues(cohortEditLogic({ id }))
    const { setExpanded, setActions, insertAfter, setTitlePlaceholder, setTitleStatus } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder(cohort?.name || 'Cohort')
        setTitleStatus(
            cohort
                ? {
                      label: cohort.is_static ? 'Static' : 'Dynamic',
                      type: 'default',
                  }
                : null
        )
        setActions(
            !cohortMissing
                ? [
                      {
                          text: 'People in cohort',
                          icon: <IconPerson />,
                          onClick: () => {
                              setExpanded(false)
                              insertAfter({
                                  type: NotebookNodeType.Query,
                                  attrs: {
                                      query: {
                                          kind: NodeKind.DataTableNode,
                                          source: {
                                              kind: NodeKind.ActorsQuery,
                                              properties: [
                                                  {
                                                      type: PropertyFilterType.Cohort,
                                                      key: 'id',
                                                      value: id,
                                                  },
                                              ],
                                          },
                                          full: true,
                                      },
                                  },
                              })
                          },
                      },
                      {
                          text: 'Cohort trends',
                          icon: <IconTrends color="currentColor" />,
                          onClick: () => {
                              setExpanded(false)
                              insertAfter({
                                  type: NotebookNodeType.Query,
                                  attrs: {
                                      query: {
                                          kind: 'InsightVizNode',
                                          source: {
                                              kind: 'TrendsQuery',
                                              filterTestAccounts: true,
                                              series: [
                                                  {
                                                      kind: 'EventsNode',
                                                      event: '$pageview',
                                                      name: '$pageview',
                                                      math: 'total',
                                                  },
                                              ],
                                              interval: 'day',
                                              trendsFilter: {
                                                  display: 'ActionsLineGraph',
                                              },
                                              properties: {
                                                  type: 'AND',
                                                  values: [
                                                      {
                                                          type: 'AND',
                                                          values: [
                                                              {
                                                                  key: 'id',
                                                                  value: id,
                                                                  type: 'cohort',
                                                              },
                                                          ],
                                                      },
                                                  ],
                                              },
                                          },
                                      },
                                  },
                              })
                          },
                      },
                  ]
                : []
        )
    }, [cohort, cohortMissing, id, insertAfter, setActions, setExpanded, setTitlePlaceholder, setTitleStatus])

    return null
}

const Component = ({ attributes }: NotebookNodeProps<CohortNotebookWidgetAttributes>): JSX.Element => {
    const { id } = attributes

    const { expanded } = useValues(notebookNodeLogic)
    const { cohort, cohortLoading, cohortMissing, query } = useValues(cohortEditLogic({ id }))
    const { setQuery } = useActions(cohortEditLogic({ id }))

    const modifiedQuery = useMemo<DataTableNode>(() => {
        return {
            ...query,
            embedded: true,
            // TODO: Add back in controls in a way that actually works - maybe sync with NotebookNodeQuery
            full: false,
            showElapsedTime: false,
            showTimings: false,
            showOpenEditorButton: false,
        }
    }, [query])

    if (cohortMissing) {
        return <NotFound object="cohort" />
    }
    return (
        <div className="flex flex-col overflow-hidden">
            <div className={clsx('p-4 gap-2', !expanded && 'cursor-pointer')}>
                {cohortLoading ? (
                    <LemonSkeleton className="h-6" />
                ) : (
                    <span className="text-secondary">
                        {cohort.count} {cohort.count === 1 ? 'person' : 'persons'}
                    </span>
                )}
            </div>

            {expanded ? (
                <>
                    <LemonDivider className="my-0" />
                    <Query query={modifiedQuery} setQuery={setQuery} />
                </>
            ) : null}
        </div>
    )
}

export const NotebookNodeCohort = createPostHogWidgetNode<CohortNotebookWidgetAttributes>({
    nodeType: NotebookNodeType.Cohort,
    titlePlaceholder: 'Cohort',
    editableTitle: false,
    Component,
    ToolbarComponent: CohortNotebookToolbar,
    heightEstimate: 300,
    minHeight: 100,
    href: (attrs) => urls.cohort(attrs.id),
    attributes: {
        id: {},
        view: {},
    },
    defaultView: getNotebookWidgetDefaultView('Cohort'),
    views: COHORT_NOTEBOOK_WIDGET_VIEWS,
    serializedText: (attrs) => {
        const title = attrs?.title || ''
        const id = attrs?.id || ''
        return `${title} ${id}`.trim()
    },
})
