import { connect, kea, key, LogicWrapper, path, props, selectors } from 'kea'
import { uuid } from 'lib/utils'
import { errorTrackingIssueEventsQuery } from 'scenes/error-tracking/queries'

import { ErrorTrackingRelationalIssue, EventsQuery } from '~/queries/schema/schema-general'

import { DataQueryLogic } from '../DataTable'
import { errorFiltersLogic } from '../ErrorFilters/errorFiltersLogic'
import type { eventsQueryLogicType } from './eventsQueryLogicType'

export interface EventDataLogicProps {
    issueId: ErrorTrackingRelationalIssue['id']
}

export const eventsQueryLogic: LogicWrapper<DataQueryLogic<EventsQuery>> = kea<eventsQueryLogicType>([
    path((key) => ['scenes', 'error-tracking', 'eventsQueryLogic', key]),
    props({} as EventDataLogicProps),
    key((props) => props.issueId),

    connect(() => {
        return {
            values: [errorFiltersLogic, ['filterTestAccounts', 'searchQuery', 'filterGroup', 'dateRange']],
        }
    }),

    selectors({
        query: [
            (s) => [(_, props) => props.issueId, s.filterTestAccounts, s.searchQuery, s.filterGroup, s.dateRange],
            (issueId, filterTestAccounts, searchQuery, filterGroup, dateRange) =>
                errorTrackingIssueEventsQuery({
                    issueId,
                    filterTestAccounts,
                    filterGroup,
                    searchQuery,
                    dateRange,
                    columns: ['*', 'timestamp', 'person'],
                }),
        ],
        queryKey: [
            (s) => [s.query],
            () => {
                return uuid()
            },
        ],
    }),
])
