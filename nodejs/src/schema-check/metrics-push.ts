import { SqlxShadowResult, describeError } from './check'

export const PUSH_TIMEOUT_MS = 3000

export interface PushTarget {
    pushgatewayUrl: string
    app: string
}

export type FetchFunction = (url: string, init: RequestInit) => Promise<Response>

// The charts alert rules read these names. Error, dirty and skipped results get no sample, so they
// can never replace an earlier "missing" with 0.
export function renderMetrics(djangoExitCode: number, sqlx: SqlxShadowResult[], nowSeconds: number): string {
    const sqlxSamples = sqlx
        .filter((result) => result.status === 'satisfied' || result.status === 'missing')
        .map(
            (result) =>
                `node_schema_check_sqlx_missing{database="${result.requirement.database}"} ${result.status === 'missing' ? 1 : 0}`
        )
    return (
        [
            '# TYPE node_schema_check_last_run_timestamp_seconds gauge',
            `node_schema_check_last_run_timestamp_seconds ${nowSeconds}`,
            '# TYPE node_schema_check_django_exit_code gauge',
            `node_schema_check_django_exit_code ${djangoExitCode}`,
            ...(sqlxSamples.length > 0 ? ['# TYPE node_schema_check_sqlx_missing gauge', ...sqlxSamples] : []),
        ].join('\n') + '\n'
    )
}

// A failed push only logs, because the Pushgateway being down must never block a rollout.
export async function pushMetrics(
    body: string,
    target: PushTarget,
    fetch: FetchFunction,
    logError: (message: string) => void
): Promise<void> {
    const url = `${target.pushgatewayUrl.replace(/\/+$/, '')}/metrics/job/node_schema_check/node_app/${encodeURIComponent(target.app)}`
    try {
        const response = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'text/plain; version=0.0.4' },
            body,
            signal: AbortSignal.timeout(PUSH_TIMEOUT_MS),
        })
        if (!response.ok) {
            logError(`Warning: schema check metrics push failed with HTTP ${response.status}`)
        }
    } catch (error) {
        logError(
            `Warning: schema check metrics push failed: ${describeError(error instanceof Error ? error : new Error(String(error)))}`
        )
    }
}
