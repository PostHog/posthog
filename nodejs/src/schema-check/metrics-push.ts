import { SqlxShadowResult, describeError } from './check'

export const PUSH_TIMEOUT_MS = 3000

export interface SchemaCheckResult {
    djangoExitCode: number
    djangoMissingMigrations: number
    djangoWaitSeconds: number
    sqlx: SqlxShadowResult[]
}

export interface PushTarget {
    pushgatewayUrl: string
    app: string
}

export type FetchFunction = (url: string, init: RequestInit) => Promise<Response>

export interface PushDependencies {
    fetch: FetchFunction
    log: (message: string) => void
    logError: (message: string) => void
}

function gauge(name: string, samples: string[]): string[] {
    if (samples.length === 0) {
        return []
    }
    return [`# TYPE ${name} gauge`, ...samples]
}

export function renderMetrics(result: SchemaCheckResult, nowSeconds: number): string {
    const checked = result.sqlx.filter((item) => item.status !== 'skipped')
    const lines = [
        ...gauge('node_schema_check_last_run_timestamp_seconds', [
            `node_schema_check_last_run_timestamp_seconds ${nowSeconds}`,
        ]),
        ...gauge('node_schema_check_django_exit_code', [`node_schema_check_django_exit_code ${result.djangoExitCode}`]),
        ...gauge('node_schema_check_django_missing_migrations', [
            `node_schema_check_django_missing_migrations ${result.djangoMissingMigrations}`,
        ]),
        ...gauge('node_schema_check_django_wait_seconds', [
            `node_schema_check_django_wait_seconds ${result.djangoWaitSeconds}`,
        ]),
        ...gauge(
            'node_schema_check_sqlx_missing_versions',
            checked.map(
                (item) =>
                    `node_schema_check_sqlx_missing_versions{database="${item.requirement.database}"} ${item.missingVersions.length}`
            )
        ),
        ...gauge(
            'node_schema_check_sqlx_error',
            checked.map((item) => {
                const failed = item.status === 'error' || item.status === 'dirty' ? 1 : 0
                return `node_schema_check_sqlx_error{database="${item.requirement.database}"} ${failed}`
            })
        ),
    ]
    return lines.join('\n') + '\n'
}

export function buildPushUrl(target: PushTarget): string {
    const base = target.pushgatewayUrl.replace(/\/+$/, '')
    return `${base}/metrics/job/node_schema_check/node_app/${encodeURIComponent(target.app)}`
}

// A failed push only logs, because the Pushgateway being down must never block a rollout.
export async function pushMetrics(
    result: SchemaCheckResult,
    target: PushTarget | null,
    deps: PushDependencies
): Promise<void> {
    if (target === null) {
        deps.log('Schema check metrics push skipped, SCHEMA_CHECK_PUSHGATEWAY_URL or SCHEMA_CHECK_APP is not set')
        return
    }
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), PUSH_TIMEOUT_MS)
    try {
        const response = await deps.fetch(buildPushUrl(target), {
            method: 'PUT',
            headers: { 'Content-Type': 'text/plain; version=0.0.4' },
            body: renderMetrics(result, Math.floor(Date.now() / 1000)),
            signal: controller.signal,
        })
        if (!response.ok) {
            deps.logError(`Warning: schema check metrics push failed with HTTP ${response.status}`)
        }
    } catch (error) {
        const reason = describeError(error instanceof Error ? error : new Error(String(error)))
        deps.logError(`Warning: schema check metrics push failed: ${reason}`)
    } finally {
        clearTimeout(timeout)
    }
}
