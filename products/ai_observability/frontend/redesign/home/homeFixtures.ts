import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckStatusEnumApi,
    TraceMetricBucketSizeApi,
    TraceMetricChangeToneApi,
    TraceMetricChangeUnitApi,
    TraceMetricKeyApi,
    TraceMetricStatusApi,
    type InstrumentationCheckApi,
    type InstrumentationChecklistApi,
    type TraceMetricsApi,
    type TraceMetricTileApi,
} from '../../generated/api.schemas'

const DAYS = 7
const DOCS_URL = 'https://posthog.com/docs/ai-observability'

function trend(base: number, step: number): number[] {
    return Array.from({ length: DAYS }, (_, index) => base + step * index + (index % 2) * step)
}

export const RANGE_TOO_LONG_DETAIL = 'This range is too long to compute. Try a shorter one.'

type TileWithoutSeries = Omit<TraceMetricTileApi, 'series' | 'detail' | 'latencyQuantiles' | 'insightQuery'>

const OK_TILES: TileWithoutSeries[] = [
    {
        key: TraceMetricKeyApi.Cost,
        label: 'Cost',
        value: 1204,
        previous: 1075,
        change: 12,
        changeUnit: TraceMetricChangeUnitApi.Percent,
        changeTone: TraceMetricChangeToneApi.Neutral,
        status: TraceMetricStatusApi.Ok,
        docsUrl: null,
        setupLabel: null,
    },
    {
        key: TraceMetricKeyApi.Users,
        label: 'Users',
        value: 3410,
        previous: 3279,
        change: 4,
        changeUnit: TraceMetricChangeUnitApi.Percent,
        changeTone: TraceMetricChangeToneApi.Neutral,
        status: TraceMetricStatusApi.Ok,
        docsUrl: null,
        setupLabel: null,
    },
    {
        key: TraceMetricKeyApi.Sessions,
        label: 'Sessions',
        value: 8120,
        previous: 8300,
        change: -2.2,
        changeUnit: TraceMetricChangeUnitApi.Percent,
        changeTone: TraceMetricChangeToneApi.Neutral,
        status: TraceMetricStatusApi.Ok,
        docsUrl: null,
        setupLabel: null,
    },
    {
        key: TraceMetricKeyApi.Traces,
        label: 'Traces',
        value: 52118,
        previous: 47810,
        change: 9,
        changeUnit: TraceMetricChangeUnitApi.Percent,
        changeTone: TraceMetricChangeToneApi.Neutral,
        status: TraceMetricStatusApi.Ok,
        docsUrl: null,
        setupLabel: null,
    },
    {
        key: TraceMetricKeyApi.ErrorRate,
        label: 'Error rate',
        value: 0.022,
        previous: 0.018,
        change: 0.4,
        changeUnit: TraceMetricChangeUnitApi.Points,
        changeTone: TraceMetricChangeToneApi.Bad,
        status: TraceMetricStatusApi.Ok,
        docsUrl: null,
        setupLabel: null,
    },
    {
        key: TraceMetricKeyApi.P95Latency,
        label: 'p95 latency',
        value: 4.2,
        previous: 4.5,
        change: -0.3,
        changeUnit: TraceMetricChangeUnitApi.Seconds,
        changeTone: TraceMetricChangeToneApi.Good,
        status: TraceMetricStatusApi.Ok,
        docsUrl: null,
        setupLabel: null,
    },
]

const SERIES: Record<TraceMetricKeyApi, number[]> = {
    [TraceMetricKeyApi.Cost]: trend(120, 25),
    [TraceMetricKeyApi.Users]: trend(400, 40),
    [TraceMetricKeyApi.Sessions]: trend(1000, 60),
    [TraceMetricKeyApi.Traces]: trend(6000, 500),
    [TraceMetricKeyApi.ErrorRate]: trend(0.014, 0.001),
    [TraceMetricKeyApi.P95Latency]: trend(3.6, 0.2),
}

const DETAILS: Record<TraceMetricKeyApi, string | null> = {
    [TraceMetricKeyApi.Cost]: 'Spend across all models',
    [TraceMetricKeyApi.Users]: 'Identified people with at least one trace',
    [TraceMetricKeyApi.Sessions]: '6.4 traces per session',
    [TraceMetricKeyApi.Traces]: '7,445 per day on average',
    [TraceMetricKeyApi.ErrorRate]: '1,147 errored traces',
    [TraceMetricKeyApi.P95Latency]: null,
}

function metricsOf(tiles: TileWithoutSeries[]): TraceMetricsApi {
    return {
        dateFrom: '2026-11-12T00:00:00Z',
        dateTo: '2026-11-19T00:00:00Z',
        previousDateFrom: '2026-11-05T00:00:00Z',
        previousDateTo: '2026-11-12T00:00:00Z',
        bucketSize: TraceMetricBucketSizeApi.Day,
        bucketStarts: Array.from(
            { length: DAYS },
            (_, index) => `2026-11-${String(12 + index).padStart(2, '0')}T00:00:00Z`
        ),
        tiles: tiles.map((tile) => ({
            ...tile,
            detail: DETAILS[tile.key],
            latencyQuantiles: tile.key === TraceMetricKeyApi.P95Latency ? { p50Seconds: 1.4, p99Seconds: 8.9 } : null,
            series: SERIES[tile.key],
            insightQuery: `SELECT toStartOfDay(now()) AS bucket, 0 AS value -- ${tile.key}`,
        })),
    }
}

export const METRICS: TraceMetricsApi = metricsOf(OK_TILES)

const SETUP_GUIDES: Partial<Record<TraceMetricKeyApi, Pick<TraceMetricTileApi, 'docsUrl' | 'setupLabel'>>> = {
    [TraceMetricKeyApi.Cost]: { setupLabel: 'Track costs', docsUrl: `${DOCS_URL}/calculating-costs` },
    [TraceMetricKeyApi.Users]: { setupLabel: 'Identify users', docsUrl: `${DOCS_URL}/installation` },
    [TraceMetricKeyApi.Sessions]: { setupLabel: 'Add session IDs', docsUrl: `${DOCS_URL}/sessions` },
    [TraceMetricKeyApi.P95Latency]: { setupLabel: 'Capture latency', docsUrl: `${DOCS_URL}/installation` },
}

export const METRICS_NOT_SET_UP: TraceMetricsApi = metricsOf(
    OK_TILES.map((tile) => {
        const guide = SETUP_GUIDES[tile.key]
        return guide
            ? {
                  ...tile,
                  value: null,
                  previous: null,
                  change: null,
                  changeTone: TraceMetricChangeToneApi.Neutral,
                  status: TraceMetricStatusApi.NotSetUp,
                  ...guide,
              }
            : tile
    })
)

export const TILE_LINKS: Partial<Record<TraceMetricKeyApi, string>> = {
    [TraceMetricKeyApi.Traces]: '/ai-observability/traces',
    [TraceMetricKeyApi.ErrorRate]: '/ai-observability/errors',
}

const CHECKLIST_DOCS_URL = 'https://posthog.com/docs/ai-observability/installation'

function check(
    key: AIObservabilityInstrumentationCheckEnumApi,
    title: string,
    status: InstrumentationCheckStatusEnumApi,
    detail: string
): InstrumentationCheckApi {
    return { key, status, title, detail, docs_url: CHECKLIST_DOCS_URL, stats: {} }
}

const { Sessions, ToolCalls, UserIdentity, TraceStructure } = AIObservabilityInstrumentationCheckEnumApi
const { Ok, Warning, Pending, Dismissed } = InstrumentationCheckStatusEnumApi

export const CHECKLIST_ALL_OK: InstrumentationChecklistApi = {
    window_days: 30,
    agent_prompt: null,
    passing: 4,
    total: 4,
    checks: [
        check(Sessions, 'Sessions', Ok, 'Generations carry a session id.'),
        check(ToolCalls, 'Tool calls', Ok, 'Tool calls appear in traces.'),
        check(UserIdentity, 'User identity', Ok, 'Generations carry a distinct id.'),
        check(TraceStructure, 'Trace structure', Ok, 'Spans nest under their traces.'),
    ],
}

export const CHECKLIST_WARNING: InstrumentationChecklistApi = {
    window_days: 30,
    agent_prompt: 'Add a session id to every generation. Docs: https://posthog.com/docs/ai-observability/installation',
    passing: 3,
    total: 4,
    checks: [
        check(Sessions, 'Sessions', Warning, 'No generations carry a session id. Send $ai_session_id.'),
        check(ToolCalls, 'Tool calls', Ok, 'Tool calls appear in traces.'),
        check(UserIdentity, 'User identity', Dismissed, 'Marked as not applicable.'),
        check(TraceStructure, 'Trace structure', Ok, 'Spans nest under their traces.'),
    ],
}

export const CHECKLIST_PENDING: InstrumentationChecklistApi = {
    window_days: 30,
    agent_prompt: null,
    passing: 3,
    total: 4,
    checks: [
        check(Sessions, 'Sessions', Pending, 'Not enough generations to grade yet.'),
        check(ToolCalls, 'Tool calls', Ok, 'Tool calls appear in traces.'),
        check(UserIdentity, 'User identity', Dismissed, 'Marked as not applicable.'),
        check(TraceStructure, 'Trace structure', Ok, 'Spans nest under their traces.'),
    ],
}
