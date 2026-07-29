import { Counter } from 'prom-client'

const fetchTotal = new Counter({
    name: 'integration_gateway_fetch_total',
    help: 'Credential-fetch requests. result: ok | error. caller = the JWT caller claim.',
    labelNames: ['caller', 'result'],
})

const refreshTotal = new Counter({
    name: 'integration_gateway_refresh_total',
    help: 'Token-refresh outcomes. result: refreshed | failed | locked | skipped | backoff | superseded. kind = integration kind.',
    labelNames: ['kind', 'result'],
})

export function recordFetch(caller: string, result: 'ok' | 'error'): void {
    fetchTotal.inc({ caller, result })
}

export function recordRefresh(
    kind: string,
    result: 'refreshed' | 'failed' | 'locked' | 'skipped' | 'backoff' | 'superseded'
): void {
    refreshTotal.inc({ kind, result })
}
