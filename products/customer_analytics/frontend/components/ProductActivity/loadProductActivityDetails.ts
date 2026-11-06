import {
    NodeKind,
    type BookActivityInterval,
    type BookActivityPeopleResult,
    type BookActivityPeopleQuery,
    type BookActivityFirstsQuery,
    type BookActivityFirstsResult,
    type DateRange,
} from '~/queries/schema/schema-general'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { ActivityQueryRequest } from './activityQueryRequest'

export interface ProductActivityDetails {
    people: BookActivityPeopleResult | null
    firsts: BookActivityFirstsResult | null
}

export async function loadProductActivityDetails(
    request: ActivityQueryRequest,
    options: {
        accountIds: string[]
        dateRange: DateRange
        interval: BookActivityInterval
        peopleLimit: number
        includePeople: boolean
        includeFirstUse: boolean
        previousPeople?: BookActivityPeopleResult | null
        rowLimit?: number
    }
): Promise<ProductActivityDetails> {
    const common = {
        accountIds: options.accountIds,
        ...(options.rowLimit === undefined ? {} : { rowLimit: options.rowLimit }),
        tags: CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
    }
    const [people, firsts] = await Promise.all([
        options.includePeople
            ? options.previousPeople
                ? Promise.resolve(options.previousPeople)
                : request
                      .perform<BookActivityPeopleQuery>({
                          ...common,
                          kind: NodeKind.BookActivityPeopleQuery,
                          dateRange: options.dateRange,
                          interval: options.interval,
                          peopleLimit: options.peopleLimit,
                      })
                      .then((response) => response.results)
            : Promise.resolve(null),
        options.includeFirstUse
            ? request
                  .perform<BookActivityFirstsQuery>({ ...common, kind: NodeKind.BookActivityFirstsQuery })
                  .then((response) => response.results)
            : Promise.resolve(null),
    ])
    return { people, firsts }
}
