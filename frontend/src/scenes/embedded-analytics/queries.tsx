import { ChartAxis } from '~/queries/schema/schema-general'

export interface QueryConfig {
    dateFrom: string
    dateTo: string
    requestNameBreakdownEnabled: boolean
    requestNameFilter: string[]
}

const createRequestNameFilterClause = (requestNameFilter: string[]): string => {
    if (requestNameFilter.length === 0) {
        return ''
    }

    const escapedNames = requestNameFilter.map((name) => `'${name.replace(/'/g, "''")}'`).join(', ')
    return `and name in (${escapedNames})`
}

export const createExpensiveQueriesColumns = (requestNameBreakdownEnabled: boolean): ChartAxis[] => {
    const baseColumns = [
        {
            column: 'query_start_time',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query_duration_ms',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'read_tb',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'cpu_sec',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'created_by',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
    ]

    return requestNameBreakdownEnabled
        ? [
              ...baseColumns,
              {
                  column: 'name',
                  settings: { formatting: { prefix: '', suffix: '' } },
              },
          ]
        : baseColumns
}

export const createLast20QueriesColumns = (requestNameBreakdownEnabled: boolean): ChartAxis[] => {
    const baseColumns = [
        {
            column: 'finished_at',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query_duration_ms',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'created_by',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
    ]

    return requestNameBreakdownEnabled
        ? [
              ...baseColumns,
              {
                  column: 'name',
                  settings: { formatting: { prefix: '', suffix: '' } },
              },
          ]
        : baseColumns
}

export const createFailedQueriesColumns = (): ChartAxis[] => {
    return [
        {
            column: 'finished_at',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query_id',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'endpoint',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'query_duration_ms',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'name',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'read_tb',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'human_readable_read_size',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'cpu_sec',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'memory_usage',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'status',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'exception_code',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
        {
            column: 'exception_name',
            settings: { formatting: { prefix: '', suffix: '' } },
        },
    ]
}

export const createApiQueriesCountQuery = ({
    dateFrom,
    dateTo,
    requestNameBreakdownEnabled,
    requestNameFilter,
}: QueryConfig): string => `
    select 
        event_date, 
        ${requestNameBreakdownEnabled ? 'name,' : ''} 
        count(1) as number_of_queries
    from query_log
    where is_personal_api_key_request 
        and event_date >= '${dateFrom}' 
        and event_date <= '${dateTo}'
        ${createRequestNameFilterClause(requestNameFilter)}
    group by event_date ${requestNameBreakdownEnabled ? ', name' : ''}
    order by event_date asc ${requestNameBreakdownEnabled ? ', name asc' : ''}`

export const createApiReadTbQuery = ({
    dateFrom,
    dateTo,
    requestNameBreakdownEnabled,
    requestNameFilter,
}: QueryConfig): string => `
    select 
        event_date, 
        ${requestNameBreakdownEnabled ? 'name,' : ''}
        sum(read_bytes)/1e12 as read_tb
    from query_log
    where 
        is_personal_api_key_request 
        and event_date >= '${dateFrom}' 
        and event_date <= '${dateTo}'
        ${createRequestNameFilterClause(requestNameFilter)}
    group by event_date ${requestNameBreakdownEnabled ? ', name' : ''}
    order by event_date asc ${requestNameBreakdownEnabled ? ', name asc' : ''}`

export const createApiCpuSecondsQuery = ({
    dateFrom,
    dateTo,
    requestNameBreakdownEnabled,
    requestNameFilter,
}: QueryConfig): string => `
    select 
        event_date, 
        ${requestNameBreakdownEnabled ? 'name,' : ''}
        sum(cpu_microseconds)/1e6 as cpu_sec
    from query_log
    where 
        is_personal_api_key_request 
        and event_date >= '${dateFrom}' 
        and event_date <= '${dateTo}'
        ${createRequestNameFilterClause(requestNameFilter)}
    group by event_date ${requestNameBreakdownEnabled ? ', name' : ''}
    order by event_date asc ${requestNameBreakdownEnabled ? ', name asc' : ''}`

export const createApiQueriesPerKeyQuery = ({ dateFrom, dateTo }: QueryConfig): string => `
    select 
        event_date, 
        api_key_label, 
        count(1) as total_queries
    from query_log 
    where 
        event_date >= '${dateFrom}'
        and event_date <= '${dateTo}'
        and is_personal_api_key_request
    group by event_date, api_key_label
    order by event_date`

export const createLast20QueriesQuery = ({
    dateFrom,
    dateTo,
    requestNameBreakdownEnabled,
    requestNameFilter,
}: QueryConfig): string => `
    select 
        event_time as finished_at, 
        ${requestNameBreakdownEnabled ? 'name,' : ''}
        query, 
        query_duration_ms, 
        api_key_label,
        created_by 
    from query_log
    where
        is_personal_api_key_request
        and event_date >= '${dateFrom}'
        and event_date <= '${dateTo}'
        ${createRequestNameFilterClause(requestNameFilter)}
    order by event_time desc
    limit 20`

export const createExpensiveQueriesQuery = ({
    dateFrom,
    dateTo,
    requestNameBreakdownEnabled,
    requestNameFilter,
}: QueryConfig): string => `
    select 
        query_start_time, 
        ${requestNameBreakdownEnabled ? 'name,' : ''}
        query,
        query_duration_ms,
        api_key_label,
        read_bytes / 1e12 as read_tb,
        formatReadableSize(read_bytes) as human_readable_read_size,
        cpu_microseconds / 1e6 as cpu_sec,
        memory_usage,
        created_by
    from query_log
    where 
        is_personal_api_key_request
        and event_date >= '${dateFrom}'
        and event_date <= '${dateTo}'
        ${createRequestNameFilterClause(requestNameFilter)}
    order by read_tb desc, event_time desc
    limit 25`

export const createFailedQueriesQuery = ({ dateFrom, dateTo }: QueryConfig): string => `
    select 
        event_time as finished_at,
        query_id,
        endpoint,
        query, 
        query_duration_ms,
        name,
        read_bytes / 1e12 as read_tb,
        formatReadableSize(read_bytes) as human_readable_read_size,
        cpu_microseconds / 1e6 as cpu_sec,
        memory_usage,
        status,
        exception_code, 
        exception_name,
    from query_log 
    where 
        is_personal_api_key_request
        and exception_code != 0 
        and event_date >= '${dateFrom}'
        and event_date <= '${dateTo}'
    order by read_tb desc, event_time desc
    limit 25`
