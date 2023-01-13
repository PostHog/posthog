import { InsightQueryNode, TrendsQuery } from '~/queries/schema'
import { ActionType, ChartDisplayType } from '~/types'
import { seriesToActionsAndEvents } from '../InsightQuery/utils/queryNodeToFilter'
import { getEventNamesForAction } from 'lib/utils'
import { isStickinessQuery, isTrendsQuery } from '~/queries/utils'

export const getAllEventNames = (query: InsightQueryNode, allActions: ActionType[]): string[] => {
    const { actions, events } = seriesToActionsAndEvents((query as TrendsQuery).series || [])

    const allEvents = [
        ...events.map((e) => String(e.id)),
        ...actions.flatMap((action) => getEventNamesForAction(action.id as string | number, allActions)),
    ]

    // remove duplicates and empty events
    return Array.from(new Set(allEvents.filter((a): a is string => !!a)))
}

export const getDisplay = (query: InsightQueryNode): ChartDisplayType | undefined => {
    if (isStickinessQuery(query)) {
        return query.stickinessFilter?.display
    } else if (isTrendsQuery(query)) {
        return query.trendsFilter?.display
    } else {
        return undefined
    }
}
