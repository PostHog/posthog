import { LemonTag } from '@posthog/lemon-ui'

interface SpecViewProps {
    spec: Record<string, unknown> | null
}

export function SpecSummary({ spec }: SpecViewProps): JSX.Element | null {
    if (!spec) {
        return null
    }
    const normalized = normalizeSpec(spec)

    const target = stringOrNull(normalized.target)
    const model = stringOrNull(normalized.model)
    const threshold = normalized.ship_threshold
    const metric = normalized.metric
    const formattedThreshold = formatThreshold(threshold)
    const lookback = pickWindow(normalized, 'lookback')
    const prediction = pickWindow(normalized, 'prediction')
    const lookbackRaw = pickRawWindow(normalized, 'lookback')
    const predictionRaw = pickRawWindow(normalized, 'prediction')

    const consumed = new Set([
        'target',
        'target_column',
        'model',
        'lookback_window',
        'prediction_window',
        'predict_window',
        'windows',
        'feature_window',
        'target_window',
        'cutoff',
        'metric',
    ])
    // Only consume ship_threshold when we successfully formatted it. Otherwise let it
    // fall through to "Other settings" so the user can at least see the raw shape.
    if (formattedThreshold) {
        consumed.add('ship_threshold')
    }
    const extras = Object.entries(normalized).filter(([k]) => !consumed.has(k))

    const showHero = target !== null || model !== null || formattedThreshold !== null
    const showTimeline = lookback !== null || prediction !== null
    if (!showHero && !showTimeline && extras.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-4">
            <SpecHero target={target} model={model} threshold={formattedThreshold} />
            <TaskInfo lookback={lookbackRaw} prediction={predictionRaw} metric={metric} />
            {extras.length > 0 && <OtherSettings entries={extras} />}
        </div>
    )
}

function TaskInfo({
    lookback,
    prediction,
    metric,
}: {
    lookback: unknown
    prediction: unknown
    metric: unknown
}): JSX.Element | null {
    const { start: lookStart, end: lookEnd } = parseRangeDays(lookback)!
    const { start: predStart, end: predEnd } = parseRangeDays(prediction)!
    return (
        <div className="border rounded p-5 bg-bg-light flex flex-col gap-2">
            <div className="text-xs text-muted uppercase tracking-wide">Task info</div>
            <div className="text-xs flex items-baseline gap-1.5 px-2 bg-bg-light">
                <span className="text-muted">Training window:</span>
                <span className="font-mono">{formatOffset(lookStart) + ' - ' + formatOffset(lookEnd)}</span>
            </div>
            <div className="text-xs flex items-baseline gap-1.5 px-2 bg-bg-light">
                <span className="text-muted">Test window:</span>
                <span className="font-mono">{formatOffset(predStart) + ' - ' + formatOffset(predEnd)}</span>
            </div>
            <div className="text-xs flex items-baseline gap-1.5 px-2 bg-bg-light">
                <span className="text-muted">Metric:</span>
                <span className="font-mono">{formatExtraValue(metric)}</span>
            </div>
        </div>
    )
}

function SpecHero({
    target,
    model,
    threshold,
}: {
    target: string | null
    model: string | null
    threshold: { metric: string; value: string } | null
}): JSX.Element {
    return (
        <div className="border rounded p-5 bg-bg-light flex flex-col gap-2">
            <div className="text-xs text-muted uppercase tracking-wide">Goal</div>
            <div className="text-xl font-semibold leading-tight">
                {target ? (
                    <>
                        Predict <span className="font-mono">{target}</span>
                    </>
                ) : (
                    <span className="text-muted">Untitled task</span>
                )}
            </div>
            <div className="flex flex-wrap gap-2 mt-1">
                {model && <LemonTag type="completion">model: {model}</LemonTag>}
                {threshold && (
                    <LemonTag type="primary">
                        deploy on: {threshold.metric} ≥ {threshold.value}
                    </LemonTag>
                )}
            </div>
        </div>
    )
}

function formatThreshold(threshold: unknown): { metric: string; value: string } | null {
    if (threshold === null || threshold === undefined) {
        return null
    }
    const direct = cleanThresholdValue(threshold)
    if (direct !== null) {
        return { metric: 'score', value: direct }
    }
    if (typeof threshold !== 'object' || Array.isArray(threshold)) {
        return null
    }
    const obj = threshold as Record<string, unknown>

    // Pattern A: { metric: "auc", value: 0.85 } / { name: ..., score: ... } / { on: ..., at: ... }
    const explicitMetric = stringOrNull(obj.metric) ?? stringOrNull(obj.name) ?? stringOrNull(obj.on)
    const explicitValueRaw = obj.value ?? obj.score ?? obj.threshold ?? obj.at ?? obj.min ?? obj.ge ?? obj['>=']
    const explicitValue = cleanThresholdValue(explicitValueRaw)
    if (explicitValue !== null) {
        return { metric: explicitMetric ?? 'score', value: explicitValue }
    }

    // Pattern B: { test_auc: '>= 0.75' } or { auc: 0.85 } — the key IS the metric name.
    for (const [key, value] of Object.entries(obj)) {
        const cleaned = cleanThresholdValue(value)
        if (cleaned !== null) {
            return { metric: key, value: cleaned }
        }
    }

    return null
}

function cleanThresholdValue(raw: unknown): string | null {
    if (typeof raw === 'number' && Number.isFinite(raw)) {
        return raw.toFixed(3)
    }
    if (typeof raw !== 'string') {
        return null
    }
    const trimmed = raw.trim()
    if (!trimmed) {
        return null
    }
    // Strip leading comparison operator like ">= 0.75", "> 0.7", "≥ 0.75".
    const stripped = trimmed.replace(/^(>=|<=|>|<|≥|≤|=)\s*/, '').trim()
    if (!stripped) {
        return null
    }
    const asNumber = Number(stripped)
    if (Number.isFinite(asNumber)) {
        return asNumber.toFixed(3)
    }
    return stripped
}

const UNIT_TO_DAYS: Record<string, number> = {
    s: 1 / 86400,
    m: 1 / 1440,
    h: 1 / 24,
    d: 1,
    w: 7,
    M: 30,
    y: 365,
}

function parseOffsetDays(point: string): number | null {
    const cleaned = point
        .trim()
        .replace(/\s+/g, '')
        .replace(/^now\(\)/i, 'now')
    if (/^now$/i.test(cleaned)) {
        return 0
    }
    const match = cleaned.match(/^now([+-])(\d+)([smhdwMy])$/)
    if (!match) {
        return null
    }
    const sign = match[1] === '-' ? -1 : 1
    const n = parseInt(match[2], 10)
    const days = UNIT_TO_DAYS[match[3]]
    if (days === undefined) {
        return null
    }
    return sign * n * days
}

function parseRangeDays(value: unknown): { start: number; end: number } | null {
    if (typeof value !== 'string') {
        return null
    }
    const trimmed = value.trim()
    if (!trimmed) {
        return null
    }
    const rangeMatch = trimmed.match(/^[[(]\s*(.+?)\s*,\s*(.+?)\s*[\])]$/)
    if (!rangeMatch) {
        const single = parseOffsetDays(trimmed)
        if (single === null) {
            return null
        }
        return { start: single, end: single }
    }
    const a = parseOffsetDays(rangeMatch[1])
    const b = parseOffsetDays(rangeMatch[2])
    if (a === null || b === null) {
        return null
    }
    return { start: Math.min(a, b), end: Math.max(a, b) }
}

function pickRawWindow(spec: Record<string, unknown>, kind: 'lookback' | 'prediction'): unknown {
    const keys = kind === 'lookback' ? LOOKBACK_KEYS : PREDICTION_KEYS
    for (const k of keys) {
        if (spec[k] !== undefined && spec[k] !== null && spec[k] !== '') {
            return spec[k]
        }
    }
    const windows = spec.windows
    if (windows && typeof windows === 'object' && !Array.isArray(windows)) {
        const w = windows as Record<string, unknown>
        for (const k of keys) {
            if (w[k] !== undefined && w[k] !== null && w[k] !== '') {
                return w[k]
            }
        }
        if (w[kind] !== undefined && w[kind] !== null && w[kind] !== '') {
            return w[kind]
        }
    }
    return null
}

function formatDuration(days: number): string {
    const abs = Math.abs(days)
    if (abs === 0) {
        return '0 days'
    }
    if (abs >= 730) {
        const y = abs / 365
        return `${roundForDisplay(y)} ${y === 1 ? 'year' : 'years'}`
    }
    return `${roundForDisplay(abs)} ${abs === 1 ? 'day' : 'days'}`
}

function formatOffset(days: number): string {
    if (days === 0) {
        return 'now'
    }
    const pred = days < 0 ? 'ago' : 'from now'
    return `${formatDuration(days)} ${pred}`
}

function roundForDisplay(n: number): string {
    if (Number.isInteger(n)) {
        return n.toString()
    }
    return n.toFixed(1).replace(/\.0$/, '')
}

function OtherSettings({ entries }: { entries: [string, unknown][] }): JSX.Element {
    const flattened = flattenEntriesForChips(entries)
    return (
        <div>
            <div className="text-xs text-muted uppercase tracking-wide mb-2">Other settings</div>
            <div className="flex flex-wrap gap-2">
                {flattened.map(([key, value]) => (
                    <div key={key} className="text-xs flex items-baseline gap-1.5 border rounded px-2 py-1 bg-bg-light">
                        <span className="text-muted">{prettify(key)}</span>
                        <span className="font-mono">{formatExtraValue(value)}</span>
                    </div>
                ))}
            </div>
        </div>
    )
}

function flattenEntriesForChips(entries: [string, unknown][]): [string, unknown][] {
    const out: [string, unknown][] = []
    for (const [key, value] of entries) {
        if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
            const obj = value as Record<string, unknown>
            const keys = Object.keys(obj)
            // Inline shallow objects (1-4 fields) as `parent.child` chips so the user sees the real values.
            if (keys.length > 0 && keys.length <= 4 && keys.every((k) => isScalar(obj[k]))) {
                for (const k of keys) {
                    out.push([`${key}.${k}`, obj[k]])
                }
                continue
            }
        }
        out.push([key, value])
    }
    return out
}

function isScalar(value: unknown): boolean {
    return value === null || ['string', 'number', 'boolean'].includes(typeof value)
}

const LOOKBACK_KEYS = ['feature_window', 'lookback_window', 'lookback']
const PREDICTION_KEYS = ['target_window', 'prediction_window', 'predict_window', 'prediction']

function pickWindow(spec: Record<string, unknown>, kind: 'lookback' | 'prediction'): string | null {
    const keys = kind === 'lookback' ? LOOKBACK_KEYS : PREDICTION_KEYS
    const candidates: unknown[] = keys.map((k) => spec[k])
    const windows = spec.windows
    if (windows && typeof windows === 'object' && !Array.isArray(windows)) {
        for (const k of keys) {
            candidates.push((windows as Record<string, unknown>)[k])
        }
        candidates.push((windows as Record<string, unknown>)[kind])
    }
    for (const candidate of candidates) {
        if (candidate !== undefined && candidate !== null && candidate !== '') {
            return formatWindow(candidate)
        }
    }
    return null
}

function formatWindow(value: unknown): string {
    if (typeof value === 'number') {
        return value === 1 ? '1 day' : `${value} days`
    }
    if (typeof value !== 'string') {
        return String(value)
    }
    const trimmed = value.trim()
    if (!trimmed) {
        return ''
    }
    // Range syntax: [start, end] / (start, end] / [start, end) etc.
    const rangeMatch = trimmed.match(/^[[(]\s*(.+?)\s*,\s*(.+?)\s*[\])]$/)
    if (rangeMatch) {
        return `${cleanTimePoint(rangeMatch[1])} → ${cleanTimePoint(rangeMatch[2])}`
    }
    return cleanTimePoint(trimmed)
}

function cleanTimePoint(value: string): string {
    return value
        .trim()
        .replace(/now\(\)/gi, 'now')
        .replace(/\s+/g, ' ')
}

function stringOrNull(value: unknown): string | null {
    return typeof value === 'string' && value.length > 0 ? value : null
}

function formatExtraValue(value: unknown): string {
    if (value === null || value === undefined) {
        return '—'
    }
    if (typeof value === 'boolean') {
        return value ? 'true' : 'false'
    }
    if (typeof value === 'number') {
        return Number.isInteger(value) ? value.toString() : value.toFixed(4)
    }
    if (typeof value === 'string') {
        return value
    }
    if (Array.isArray(value)) {
        return value.length === 0 ? '[]' : `[${value.length} items]`
    }
    if (typeof value === 'object') {
        const keys = Object.keys(value as Record<string, unknown>)
        return keys.length === 0 ? '{}' : `{${keys.length} fields}`
    }
    return String(value)
}

export function SpecOneLiner({ spec }: SpecViewProps): JSX.Element {
    if (!spec) {
        return <span className="text-muted">no spec</span>
    }
    const normalized = normalizeSpec(spec)
    const target = normalized.target
    const model = normalized.model
    const prediction =
        normalized.prediction_window ?? normalized.predict_window ?? (normalized.windows as any)?.prediction
    const threshold = normalized.ship_threshold
    const parts: JSX.Element[] = []
    if (target) {
        parts.push(
            <span key="target">
                <span className="text-muted">target:</span> <code>{String(target)}</code>
            </span>
        )
    }
    if (model) {
        parts.push(
            <span key="model">
                <span className="text-muted">model:</span> <code>{String(model)}</code>
            </span>
        )
    }
    if (prediction) {
        parts.push(
            <span key="pred">
                <span className="text-muted">window:</span> <code>{String(prediction)}</code>
            </span>
        )
    }
    const formattedThreshold = formatThreshold(threshold)
    if (formattedThreshold) {
        parts.push(
            <span key="thr">
                <span className="text-muted">deploys {formattedThreshold.metric}&ge;</span>{' '}
                <code>{formattedThreshold.value}</code>
            </span>
        )
    }
    if (parts.length === 0) {
        return <LemonTag type="muted">spec.yaml present</LemonTag>
    }
    return <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">{parts}</div>
}

const MODEL_TYPE_KEYS = ['model', 'model_type', 'modelType', 'estimator', 'algorithm', 'algo']
const STACK_LEVEL_KEYS = ['stack_level', 'stackLevel', 'stack-level']
const FIT_ORDER_KEYS = ['fit_order', 'fitOrder', 'fit-order']

function normalizeSpec(spec: Record<string, unknown>): Record<string, unknown> {
    const out: Record<string, unknown> = { ...spec }

    // Drop fields the UI deliberately hides.
    for (const k of FIT_ORDER_KEYS) {
        delete out[k]
    }

    // Find the stack-level value under any naming variant.
    let stackLevel: unknown
    for (const k of STACK_LEVEL_KEYS) {
        if (k in out) {
            stackLevel = out[k]
            delete out[k]
        }
    }

    if (stackLevel !== undefined) {
        // Pull the model type from any of the known synonym keys, then drop them all.
        const explicit = MODEL_TYPE_KEYS.map((k) => spec[k]).find((v) => typeof v === 'string' && v.length > 0) as
            | string
            | undefined
        for (const key of MODEL_TYPE_KEYS) {
            delete out[key]
        }
        const levelNum = typeof stackLevel === 'number' ? stackLevel : Number(stackLevel)
        if (Number.isFinite(levelNum) && levelNum >= 1) {
            out.model = 'ensemble'
        } else {
            out.model = explicit ?? 'single'
        }
    }

    return out
}

function prettify(key: string): string {
    return key.replace(/_/g, ' ')
}

const SCORE_NAMES =
    /^(auc|roc_auc|pr_auc|accuracy|precision|recall|f1|f1_score|log_loss|brier|mse|rmse|mae|r2|kappa|mcc)$/i
const SCORE_PREFIXES = /^(score_|val_|test_|train_)/i
const TIME_LIKE = /(time|duration|seconds|_ms\b|elapsed|latency|started_at|ended_at|finished_at|created_at)/i
const NON_SCORE_METRIC_KEYS = /^(stack_level|fit_order|stackLevel|fitOrder)$/i

export function isScoreKey(key: string, value: unknown): boolean {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        return false
    }
    if (TIME_LIKE.test(key) || NON_SCORE_METRIC_KEYS.test(key)) {
        return false
    }
    if (SCORE_NAMES.test(key) || SCORE_PREFIXES.test(key)) {
        return true
    }
    return value >= 0 && value <= 1
}

export function extractMetrics(manifest: Record<string, unknown> | null): Record<string, number> {
    if (!manifest) {
        return {}
    }
    const metrics = manifest.metrics
    if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) {
        return {}
    }
    const out: Record<string, number> = {}
    for (const [key, value] of Object.entries(metrics as Record<string, unknown>)) {
        if (typeof value === 'number' && Number.isFinite(value)) {
            out[key] = value
        }
    }
    return out
}

export function extractScores(manifest: Record<string, unknown> | null): Record<string, number> {
    const all = extractMetrics(manifest)
    return Object.fromEntries(Object.entries(all).filter(([k, v]) => isScoreKey(k, v)))
}

export function metricSummary(manifest: Record<string, unknown> | null): string | null {
    const scores = extractScores(manifest)
    if (Object.keys(scores).length === 0) {
        return null
    }
    const preferred = ['auc', 'roc_auc', 'accuracy', 'f1', 'precision', 'recall']
    for (const key of preferred) {
        if (key in scores) {
            return `${key} ${scores[key].toFixed(3)}`
        }
    }
    const [k, v] = Object.entries(scores)[0]
    return `${k} ${v.toFixed(3)}`
}

interface MetricsInlineProps {
    manifest: Record<string, unknown> | null
}

export function MetricsInline({ manifest }: MetricsInlineProps): JSX.Element {
    const scores = extractScores(manifest)
    const entries = Object.entries(scores)
    if (entries.length === 0) {
        return <span className="text-muted">—</span>
    }
    return (
        <div className="flex flex-wrap gap-1">
            {entries.map(([key, value]) => (
                <span key={key} className="text-xs bg-bg-3000 px-1.5 py-0.5 rounded">
                    <span className="text-muted">{prettify(key)}</span>{' '}
                    <span className="font-mono">{value.toFixed(3)}</span>
                </span>
            ))}
        </div>
    )
}

interface ScoreCardsProps {
    manifest: Record<string, unknown> | null
}

export function ScoreCards({ manifest }: ScoreCardsProps): JSX.Element | null {
    const scores = extractScores(manifest)
    const entries = Object.entries(scores)
    if (entries.length === 0) {
        return null
    }
    return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {entries.map(([key, value]) => (
                <div key={key} className="border rounded p-3 bg-bg-light">
                    <div className="text-xs text-muted uppercase tracking-wide">{prettify(key)}</div>
                    <div className="text-2xl font-mono mt-1">{value.toFixed(4)}</div>
                </div>
            ))}
        </div>
    )
}

interface RunInfoGridProps {
    manifest: Record<string, unknown> | null
}

export function RunInfoGrid({ manifest }: RunInfoGridProps): JSX.Element | null {
    if (!manifest) {
        return null
    }

    const shipped = manifest.shipped
    const started = stringOrNull(manifest.started_at) ?? stringOrNull(manifest.created_at)
    const finished = stringOrNull(manifest.ended_at) ?? stringOrNull(manifest.finished_at)
    const explicitDuration =
        typeof manifest.duration === 'number'
            ? formatDurationSeconds(manifest.duration)
            : typeof manifest.duration_seconds === 'number'
              ? formatDurationSeconds(manifest.duration_seconds as number)
              : null
    const duration = explicitDuration ?? computeDuration(started, finished)

    const modelInfo = buildModelInfo(manifest)

    const consumed = new Set<string>([
        'run_id',
        'shipped',
        'started_at',
        'created_at',
        'ended_at',
        'finished_at',
        'duration',
        'duration_seconds',
        'metrics',
        ...modelInfo.consumedKeys,
    ])
    const extras = Object.entries(manifest).filter(([k]) => !consumed.has(k))

    const showStatus = shipped !== undefined
    const showTiming = started !== null || finished !== null || duration !== null
    const showModel = modelInfo.entries.length > 0

    if (!showStatus && !showTiming && !showModel && extras.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-4">
            {showStatus && <RunStatusBar shipped={shipped} />}
            {showTiming && <TimingPanel started={started} finished={finished} duration={duration} />}
            {showModel && <ModelInfoPanel entries={modelInfo.entries} />}
            {extras.length > 0 && <OtherSettings entries={extras} />}
        </div>
    )
}

function RunStatusBar({ shipped }: { shipped: unknown }): JSX.Element {
    return (
        <div className="flex flex-wrap gap-2">
            <LemonTag type={shipped ? 'success' : 'muted'}>{shipped ? 'shipped' : 'not shipped'}</LemonTag>
        </div>
    )
}

function TimingPanel({
    started,
    finished,
    duration,
}: {
    started: string | null
    finished: string | null
    duration: string | null
}): JSX.Element {
    return (
        <div className="border rounded p-4 bg-bg-light">
            <div className="text-xs text-muted uppercase tracking-wide mb-3">Timing</div>
            <div className="grid grid-cols-3 gap-4">
                <TimingCell label="Started" value={formatTimestamp(started)} />
                <TimingCell label="Finished" value={formatTimestamp(finished)} />
                <TimingCell label="Duration" value={duration ?? '—'} mono />
            </div>
        </div>
    )
}

function TimingCell({ label, value, mono }: { label: string; value: string; mono?: boolean }): JSX.Element {
    return (
        <div>
            <div className="text-xs text-muted">{label}</div>
            <div className={mono ? 'font-mono text-sm mt-0.5' : 'text-sm mt-0.5'}>{value}</div>
        </div>
    )
}

const MODEL_INFO_KEYS = [
    'query_version',
    'model_uri',
    'model_path',
    'model_class',
    'model_name',
    'model_type',
    'estimator',
    'algorithm',
    'algo',
    'hyperparameters',
    'hyperparams',
    'params',
    'features',
    'feature_names',
    'num_features',
    'num_train_examples',
    'train_size',
    'val_size',
    'test_size',
    'num_train_rows',
    'num_val_rows',
    'num_test_rows',
    'ensemble_members',
    'base_models',
    'stack_level',
    'fit_order',
]

interface ModelInfoEntry {
    key: string
    value: unknown
}

function buildModelInfo(manifest: Record<string, unknown>): { entries: ModelInfoEntry[]; consumedKeys: string[] } {
    const entries: ModelInfoEntry[] = []
    const consumed: string[] = []

    // Synthesize a "Class" entry from the stack_level the trainer writes inside metrics.
    const metrics = manifest.metrics
    if (metrics && typeof metrics === 'object' && !Array.isArray(metrics)) {
        const m = metrics as Record<string, unknown>
        const stackLevel = m.stack_level ?? m.stackLevel
        if (stackLevel !== undefined && stackLevel !== null) {
            const levelNum = typeof stackLevel === 'number' ? stackLevel : Number(stackLevel)
            const klass = Number.isFinite(levelNum) && levelNum >= 1 ? 'ensemble' : 'single model'
            entries.push({ key: 'class', value: klass })
            consumed.push('class')
        }
    }

    for (const key of MODEL_INFO_KEYS) {
        if (key in manifest) {
            entries.push({ key, value: manifest[key] })
            consumed.push(key)
        }
    }
    return { entries, consumedKeys: consumed }
}

function ModelInfoPanel({ entries }: { entries: ModelInfoEntry[] }): JSX.Element {
    return (
        <div className="border rounded p-4 bg-bg-light flex flex-col gap-3">
            <div className="text-xs text-muted uppercase tracking-wide">Model info</div>
            <div className="flex flex-col gap-2">
                {entries.map(({ key, value }) => (
                    <div key={key} className="flex items-baseline gap-3">
                        <span className="text-xs text-muted w-32 shrink-0">{prettify(key)}</span>
                        <span className="text-sm flex-1 min-w-0">{renderModelValue(key, value)}</span>
                    </div>
                ))}
            </div>
        </div>
    )
}

function renderModelValue(key: string, value: unknown): JSX.Element {
    if (value === null || value === undefined) {
        return <span className="text-muted">—</span>
    }
    if (typeof value === 'string') {
        if (key === 'query_version') {
            return <LemonTag type="completion">{stripSqlSuffix(value)}</LemonTag>
        }
        return <code className="text-xs break-all">{value}</code>
    }
    if (typeof value === 'number') {
        return <span className="font-mono">{Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4)}</span>
    }
    if (typeof value === 'boolean') {
        return <LemonTag type={value ? 'success' : 'muted'}>{String(value)}</LemonTag>
    }
    if (Array.isArray(value)) {
        if (value.length === 0) {
            return <span className="text-muted">none</span>
        }
        if (value.every((v) => typeof v === 'string')) {
            return (
                <div className="flex flex-wrap gap-1">
                    {value.map((v, i) => (
                        <LemonTag key={i} type="completion">
                            {String(v)}
                        </LemonTag>
                    ))}
                </div>
            )
        }
        return <span className="text-xs text-muted">{value.length} items</span>
    }
    if (typeof value === 'object') {
        const obj = value as Record<string, unknown>
        const objEntries = Object.entries(obj)
        if (objEntries.length === 0) {
            return <span className="text-muted">none</span>
        }
        return (
            <div className="flex flex-wrap gap-1">
                {objEntries.map(([k, v]) => (
                    <span key={k} className="text-xs bg-bg-3000 px-1.5 py-0.5 rounded inline-flex items-baseline gap-1">
                        <span className="text-muted">{k}:</span>
                        <span className="font-mono">
                            {typeof v === 'number'
                                ? Number.isInteger(v)
                                    ? v.toLocaleString()
                                    : v.toFixed(3)
                                : typeof v === 'object'
                                  ? JSON.stringify(v)
                                  : String(v)}
                        </span>
                    </span>
                ))}
            </div>
        )
    }
    return <span>{String(value)}</span>
}

function stripSqlSuffix(version: string): string {
    return version.endsWith('.sql') ? version.slice(0, -4) : version
}

function formatTimestamp(value: string | null): string {
    if (!value) {
        return '—'
    }
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) {
        return value
    }
    return date.toLocaleString()
}

function computeDuration(start: string | null, end: string | null): string | null {
    if (!start || !end) {
        return null
    }
    const ms = new Date(end).getTime() - new Date(start).getTime()
    if (!Number.isFinite(ms) || ms < 0) {
        return null
    }
    return formatDurationMs(ms)
}

function formatDurationSeconds(seconds: number): string {
    return formatDurationMs(seconds * 1000)
}

function formatDurationMs(ms: number): string {
    if (ms < 1000) {
        return `${Math.round(ms)} ms`
    }
    const s = ms / 1000
    if (s < 60) {
        return `${s.toFixed(1)} s`
    }
    const m = s / 60
    if (m < 60) {
        return `${m.toFixed(1)} min`
    }
    const h = m / 60
    return `${h.toFixed(2)} h`
}
