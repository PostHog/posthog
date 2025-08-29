import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { performQuery } from '~/queries/query'
import { ActorsQuery, FunnelsActorsQuery, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { FunnelPathType, PathType, SidePanelTab } from '~/types'

import { funnelDataLogic } from './funnelDataLogic'

type FunnelStepMoreProps = {
    stepIndex: number
}

export function FunnelStepMore({ stepIndex }: FunnelStepMoreProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(funnelDataLogic(insightProps))
    const { openSidePanel } = useActions(sidePanelLogic)

    const summarizeInsight = useSummarizeInsight()

    const stepNumber = stepIndex + 1
    const getPathUrl = useCallback(
        (funnelPathType: FunnelPathType, dropOff = false): string => {
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.PathsQuery,
                    funnelPathsFilter: {
                        funnelStep: dropOff ? stepNumber * -1 : stepNumber,
                        funnelSource: querySource!,
                        funnelPathType,
                    },
                    pathsFilter: {
                        includeEventTypes: [PathType.PageView, PathType.CustomEvent],
                    },
                    dateRange: {
                        date_from: querySource?.dateRange?.date_from,
                    },
                },
            }

            return urls.insightNew({ query })
        },
        [querySource, stepNumber]
    )

    const summarizeDropoffSessions = useCallback(async (): Promise<void> => {
        if (!querySource) {
            return
        }

        try {
            // Create a query to get users who dropped off at this step
            const funnelsActorsQuery: FunnelsActorsQuery = {
                kind: NodeKind.FunnelsActorsQuery,
                source: querySource,
                funnelStep: -stepNumber, // Negative step number for drop-offs
                includeRecordings: true,
            }

            const actorsQuery: ActorsQuery = {
                kind: NodeKind.ActorsQuery,
                source: funnelsActorsQuery,
                select: ['person', 'matched_recordings'],
            }

            // Execute the query to get dropped-off users and their session recordings
            const result = await performQuery(actorsQuery)

            // Extract session IDs from the matched recordings
            const sessionIds: string[] = []
            if (result?.results) {
                for (const row of result.results) {
                    const matchedRecordings = row[1] // matched_recordings is the second column
                    if (Array.isArray(matchedRecordings)) {
                        for (const recording of matchedRecordings) {
                            if (recording?.session_id) {
                                sessionIds.push(recording.session_id)
                            }
                        }
                    }
                }
            }

            if (sessionIds.length === 0) {
                lemonToast.info('No session recordings found for dropped-off users at this step')
                return
            }

            // Call Max with session summarization using the extracted session IDs
            const query =
                `Summarize sessions of users who dropped off at step ${stepNumber} of this funnel:\n${summarizeInsight(querySource)}\n` +
                `The specific session IDs to use are: ${sessionIds.join(', ')}`
            // Call Max with the session summarization request
            openSidePanel(SidePanelTab.Max, '!' + query)
        } catch (error) {
            posthog.captureException(error)
            lemonToast.error(`Failed to get session IDs for dropped-off users: ${error}`)
        }
    }, [querySource, stepNumber, openSidePanel, summarizeInsight])

    // Don't show paths modal if aggregating by groups - paths is user-based!
    if (querySource?.aggregation_group_type_index != undefined) {
        return null
    }

    return (
        <More
            placement="bottom-start"
            noPadding
            overlay={
                <>
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.before)}>
                            Show user paths leading to step
                        </LemonButton>
                    )}
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.between)}>
                            Show user paths between previous step and this step
                        </LemonButton>
                    )}
                    <LemonButton fullWidth to={getPathUrl(FunnelPathType.after)}>
                        Show user paths after step
                    </LemonButton>
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.after, true)}>
                            Show user paths after dropoff
                        </LemonButton>
                    )}
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.before, true)}>
                            Show user paths before dropoff
                        </LemonButton>
                    )}
                    {stepNumber > 1 && (
                        <LemonButton fullWidth onClick={summarizeDropoffSessions}>
                            Summarize sessions of users who dropped off
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}
