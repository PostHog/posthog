import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { useActions, useValues } from 'kea'
import { urls } from 'scenes/urls'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeProps } from '../Notebook/utils'
import { useMemo } from 'react'
import clsx from 'clsx'
import { NotFound } from 'lib/components/NotFound'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { IconCohort } from 'lib/lemon-ui/icons'
import { Query } from '~/queries/Query/Query'
import { LemonDivider } from '@posthog/lemon-ui'
import { DataTableNode } from '~/queries/schema'

const Component = ({ attributes, updateAttributes }: NotebookNodeProps<NotebookNodeCohortAttributes>): JSX.Element => {
    const { id } = attributes

    const { expanded } = useValues(notebookNodeLogic)
    const { setExpanded, setActions, insertAfter } = useActions(notebookNodeLogic)

    const { cohort, cohortLoading, cohortMissing, query } = useValues(cohortEditLogic({ id }))
    const { setQuery } = useActions(cohortEditLogic({ id }))

    if (cohortMissing) {
        return <NotFound object="cohort" />
    }

    // useEffect(() => {
    //     updateAttributes({
    //         title,
    //     })
    //     setActions([
    //         {
    //             text: 'Group events',
    //             onClick: () => {
    //                 setExpanded(false)
    //                 insertAfter({
    //                     type: NotebookNodeType.Query,
    //                     attrs: {
    //                         title: `Events for ${title}`,
    //                         query: {
    //                             kind: NodeKind.DataTableNode,
    //                             full: true,
    //                             source: {
    //                                 kind: NodeKind.EventsQuery,
    //                                 select: defaultDataTableColumns(NodeKind.EventsQuery),
    //                                 after: '-24h',
    //                                 properties: [
    //                                     {
    //                                         key: `$group_${groupTypeIndex}`,
    //                                         value: id,
    //                                         type: PropertyFilterType.Event,
    //                                         operator: PropertyOperator.Exact,
    //                                     },
    //                                 ],
    //                             },
    //                         },
    //                     },
    //                 })
    //             },
    //         },
    //     ])
    // }, [groupData])

    // if (!groupData && !groupDataLoading) {
    //     return <NotFound object="group" />
    // }

    const modifiedQuery = useMemo<DataTableNode>(() => {
        return {
            ...query,
            embedded: true,
            // TODO: Add back in controls in a way that actually works...
            full: false,
            showElapsedTime: false,
            showTimings: false,
        }
    }, [query])

    return (
        <div className="flex flex-col overflow-hidden">
            <div className={clsx('p-4 flex-0 flex gap-2 justify-between ', !expanded && 'cursor-pointer')}>
                {cohortLoading ? (
                    <LemonSkeleton className="h-6" />
                ) : (
                    <div className="flex items-center gap-2">
                        <IconCohort className="text-muted-alt text-lg" />
                        <span className="flex-1 font-semibold truncate">{cohort.name}</span>
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
    defaultTitle: 'Cohort',
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
