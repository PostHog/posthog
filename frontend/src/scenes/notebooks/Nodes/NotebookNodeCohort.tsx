import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, PropertyFilterType } from '~/types'
import { useActions, useValues } from 'kea'
import { urls } from 'scenes/urls'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeProps } from '../Notebook/utils'
import { useEffect, useMemo } from 'react'
import clsx from 'clsx'
import { NotFound } from 'lib/components/NotFound'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { IconCohort, IconPerson, InsightsTrendsIcon } from 'lib/lemon-ui/icons'
import { Query } from '~/queries/Query/Query'
import { LemonDivider, LemonTag } from '@posthog/lemon-ui'
import { DataTableNode, NodeKind } from '~/queries/schema'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeCohortAttributes>): JSX.Element => {
    const { id } = attributes

    const { expanded } = useValues(notebookNodeLogic)
    const { setExpanded, setActions, insertAfter, setTitlePlaceholder } = useActions(notebookNodeLogic)

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

    useEffect(() => {
        const title = cohort ? `Cohort: ${cohort.name}` : 'Cohort'

        setTitlePlaceholder(title)
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
                                              kind: NodeKind.PersonsQuery,
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
                          icon: <InsightsTrendsIcon noBackground color="currentColor" />,
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
    }, [cohort, cohortMissing])

    if (cohortMissing) {
        return <NotFound object="cohort" />
    }
    return (
        <div className="flex flex-col overflow-hidden">
            <div className={clsx('p-4 gap-2', !expanded && 'cursor-pointer')}>
                {cohortLoading ? (
                    <LemonSkeleton className="h-6" />
                ) : (
                    <div className="flex items-center gap-2">
                        <IconCohort className="text-muted-alt text-lg" />
                        <span className="flex-1 font-semibold truncate">{cohort.name}</span>
                        <span className="italic text-muted-alt">({cohort.count} persons)</span>
                        <LemonTag>{cohort.is_static ? 'Static' : 'Dynamic'}</LemonTag>
                    </div>
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

type NotebookNodeCohortAttributes = {
    id: number
}

export const NotebookNodeCohort = createPostHogWidgetNode<NotebookNodeCohortAttributes>({
    nodeType: NotebookNodeType.Cohort,
    titlePlaceholder: 'Cohort',
    Component,
    heightEstimate: 300,
    minHeight: 100,
    href: (attrs) => urls.cohort(attrs.id),
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: urls.cohort('(.+)'),
        getAttributes: async (match) => {
            return { id: parseInt(match[1]) }
        },
    },
    serializedText: (attrs) => {
        const title = attrs?.title || ''
        const id = attrs?.id || ''
        return `${title} ${id}`.trim()
    },
})
