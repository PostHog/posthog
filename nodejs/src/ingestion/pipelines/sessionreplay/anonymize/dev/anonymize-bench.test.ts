/* eslint-disable no-console */
// Synthetic-recording benchmark: TS scrubbers vs the native Rust addon, on a large rrweb message.
// Not a correctness test — it lives under dev/ and is excluded from the suite. Run explicitly:
//   un-skip the it() below, then: pnpm exec jest anonymize-bench --runInBand --testPathIgnorePatterns=
// It drives the same functions the pipeline uses (anonymizeEvent loop + runBlurJobs for TS; the
// stringify -> addon.anonymize -> parse round-trip for Rust) so the numbers include the FFI tax.
// It also dumps the fixtures to /tmp/replay-bench-*.json for the Rust dev/anonymize_bench.rs example.
import { AllowLists } from '../allow-lists'
import { anonymizeEvent } from '../anonymize-event'
import { runBlurJobs } from '../blur'
import { BlurJob, ScrubContext } from '../config'

type Rng = () => number
function mulberry32(seed: number): Rng {
    return () => {
        seed |= 0
        seed = (seed + 0x6d2b79f5) | 0
        let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
}
const int = (rng: Rng, n: number): number => Math.floor(rng() * n)
const pick = <T>(rng: Rng, xs: T[]): T => xs[int(rng, xs.length)]

const COMMON = [
    'the',
    'a',
    'to',
    'of',
    'and',
    'in',
    'is',
    'on',
    'for',
    'with',
    'as',
    'at',
    'by',
    'an',
    'be',
    'this',
    'that',
    'it',
    'from',
    'or',
    'you',
    'your',
    'we',
    'our',
]
const CONTENT = [
    'dashboard',
    'invoice',
    'checkout',
    'profile',
    'settings',
    'analytics',
    'campaign',
    'revenue',
    'session',
    'pipeline',
    'workspace',
    'notification',
    'subscription',
    'integration',
    'experiment',
    'retention',
    'funnel',
    'cohort',
    'warehouse',
    'anomaly',
    'customer',
    'billing',
    'onboarding',
    'insight',
    'metric',
    'segment',
    'property',
    'attribute',
    'timeline',
    'annotation',
]
// Realistic allow list: all the filler words plus half the content vocabulary, and a few url tokens.
const ALLOW_TEXT = [...COMMON, ...CONTENT.filter((_, i) => i % 2 === 0)]
const ALLOW_URL = ['api', 'app', 'cdn', 'static']

function sentence(rng: Rng, n: number): string {
    const words: string[] = []
    for (let i = 0; i < n; i++) {
        words.push(rng() < 0.4 ? pick(rng, COMMON) : pick(rng, CONTENT))
    }
    if (rng() < 0.08) {
        words.push(`user${int(rng, 100000)}@example.com`)
    }
    if (rng() < 0.12) {
        words.push(String(int(rng, 1000000)))
    }
    return words.join(' ')
}
function url(rng: Rng): string {
    return `https://app.example.com/${pick(rng, CONTENT)}/${pick(rng, CONTENT)}/${int(rng, 100000)}?ref=${pick(rng, CONTENT)}`
}

const TAGS = ['div', 'span', 'p', 'section', 'article', 'li', 'a', 'button', 'td', 'label']

function buildTree(rng: Rng, budget: { n: number }, depth: number): Record<string, unknown> {
    budget.n--
    const tag = pick(rng, TAGS)
    const attributes: Record<string, unknown> = { class: `col-${int(rng, 40)}` }
    if (rng() < 0.3) {
        attributes.id = `n${int(rng, 100000)}`
    }
    if (rng() < 0.4) {
        attributes['data-testid'] = `${pick(rng, CONTENT)}-${pick(rng, CONTENT)}`
    }
    if (rng() < 0.25) {
        attributes.title = sentence(rng, 3 + int(rng, 6))
    }
    if (tag === 'a') {
        attributes.href = url(rng)
    }
    const childNodes: unknown[] = []
    if (depth < 24 && budget.n > 0 && rng() < 0.75) {
        const kids = 1 + int(rng, Math.min(6, budget.n))
        for (let i = 0; i < kids && budget.n > 0; i++) {
            childNodes.push(buildTree(rng, budget, depth + 1))
        }
    } else {
        childNodes.push({ type: 3, textContent: sentence(rng, 4 + int(rng, 12)) })
    }
    return { type: 2, tagName: tag, attributes, childNodes }
}

function buildFullSnapshot(rng: Rng, targetNodes: number): Record<string, unknown> {
    const budget = { n: targetNodes }
    const roots: unknown[] = []
    while (budget.n > 0) {
        roots.push(buildTree(rng, budget, 1))
    }
    return {
        type: 2,
        data: { node: { type: 0, childNodes: roots }, initialOffset: { top: 0, left: 0 } },
    }
}

function buildMutation(rng: Rng): Record<string, unknown> {
    const texts = Array.from({ length: 1 + int(rng, 6) }, () => ({
        id: int(rng, 100000),
        value: sentence(rng, 3 + int(rng, 8)),
    }))
    const attributes = Array.from({ length: int(rng, 4) }, () => ({
        id: int(rng, 100000),
        attributes: { title: sentence(rng, 3), href: url(rng) },
    }))
    const adds = Array.from({ length: int(rng, 3) }, () => ({
        parentId: int(rng, 100000),
        nextId: null,
        node: { type: 3, textContent: sentence(rng, 3 + int(rng, 6)) },
    }))
    return { type: 3, data: { source: 0, texts, attributes, adds, removes: [] } }
}

function buildMessage(seed: number, targetNodes: number, mutations: number, inputs: number): Record<string, unknown[]> {
    const rng = mulberry32(seed)
    const events: unknown[] = [{ type: 4, data: { href: url(rng), width: 1920, height: 1080 } }]
    events.push(buildFullSnapshot(rng, targetNodes))
    for (let i = 0; i < mutations; i++) {
        events.push(buildMutation(rng))
    }
    for (let i = 0; i < inputs; i++) {
        events.push({
            type: 3,
            data: { source: 5, id: int(rng, 100000), text: sentence(rng, 2 + int(rng, 6)), isChecked: false },
        })
    }
    events.push({
        type: 6,
        data: { plugin: 'rrweb/console@1', payload: { level: 'log', payload: [sentence(rng, 8)], trace: [] } },
    })
    events.push({
        type: 6,
        data: {
            plugin: 'rrweb/network@1',
            payload: { requests: [{ name: url(rng), requestBody: 'token=secret value=42' }] },
        },
    })
    return { 'window-1': events }
}

function countNodes(msg: Record<string, unknown[]>): { elements: number; texts: number } {
    let elements = 0
    let texts = 0
    const visit = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (node.type === 2) {
            elements++
        }
        if (node.type === 3) {
            texts++
        }
        if (Array.isArray(node.childNodes)) {
            node.childNodes.forEach(visit)
        }
    }
    for (const events of Object.values(msg)) {
        for (const ev of events as any[]) {
            visit(ev?.data?.node)
        }
    }
    return { elements, texts }
}

interface Stat {
    p50: number
    p95: number
    mean: number
    min: number
}
function summarize(samples: number[]): Stat {
    const s = [...samples].sort((a, b) => a - b)
    const q = (p: number): number => s[Math.min(s.length - 1, Math.floor(p * s.length))]
    return { p50: q(0.5), p95: q(0.95), mean: s.reduce((a, b) => a + b, 0) / s.length, min: s[0] }
}
const ms = (n: number): string => n.toFixed(1)

describe('anonymize benchmark (opt-in, not run in normal suite)', () => {
    // eslint-disable-next-line jest/no-disabled-tests -- opt-in benchmark; un-skip to run locally
    it.skip('TS scrubbers vs native Rust addon on a large synthetic recording', async () => {
        const addon = require('@posthog/replay-anonymizer') as typeof import('@posthog/replay-anonymizer')
        const allow = new AllowLists(ALLOW_TEXT, ALLOW_URL)
        addon.initAnonymizer(allow.entries())

        for (const cfg of [
            { label: 'medium', nodes: 6000, mutations: 150, inputs: 40 },
            { label: 'large', nodes: 18000, mutations: 400, inputs: 80 },
        ]) {
            const message = buildMessage(1234, cfg.nodes, cfg.mutations, cfg.inputs)
            const json = JSON.stringify(message)
            require('fs').writeFileSync(`/tmp/replay-bench-${cfg.label}.json`, json)
            const sizeMb = json.length / (1024 * 1024)
            const events = (message['window-1'] as unknown[]).length
            const { elements, texts } = countNodes(message)

            const timeTs = async (): Promise<number> => {
                const clone = structuredClone(message)
                const blurJobs: BlurJob[] = []
                const ctx: ScrubContext = {
                    allow,
                    blurJobs,
                    blurCache: new Map(),
                    timing: { decompressMs: 0, recompressMs: 0 },
                }
                const t0 = performance.now()
                for (const evs of Object.values(clone)) {
                    for (const ev of evs as unknown[]) {
                        anonymizeEvent(ctx, ev)
                    }
                }
                await runBlurJobs(blurJobs)
                return performance.now() - t0
            }
            const timeRust = async (): Promise<{ total: number; stringify: number; scrub: number; parse: number }> => {
                const t0 = performance.now()
                const j = JSON.stringify(message)
                const t1 = performance.now()
                const res = await addon.anonymize(j)
                const t2 = performance.now()
                if (res.failed) {
                    throw new Error(`addon failed: ${res.error}`)
                }
                if (res.data !== null) {
                    JSON.parse(res.data)
                }
                const t3 = performance.now()
                return { total: t3 - t0, stringify: t1 - t0, scrub: t2 - t1, parse: t3 - t2 }
            }

            for (let i = 0; i < 3; i++) {
                await timeTs()
                await timeRust()
            }
            const N = 20
            const tsTimes: number[] = []
            const rust = {
                total: [] as number[],
                stringify: [] as number[],
                scrub: [] as number[],
                parse: [] as number[],
            }
            for (let i = 0; i < N; i++) {
                tsTimes.push(await timeTs())
            }
            for (let i = 0; i < N; i++) {
                const r = await timeRust()
                rust.total.push(r.total)
                rust.stringify.push(r.stringify)
                rust.scrub.push(r.scrub)
                rust.parse.push(r.parse)
            }

            const ts = summarize(tsTimes)
            const rt = summarize(rust.total)
            const rScrub = summarize(rust.scrub)
            const rStr = summarize(rust.stringify)
            const rParse = summarize(rust.parse)

            console.log(
                `\n===== ${cfg.label}: ${ms(sizeMb)} MB JSON, ${events} events, ${elements} element nodes, ${texts} text nodes, ${N} iters =====`
            )
            console.log(
                `TS   total   p50=${ms(ts.p50)}ms  p95=${ms(ts.p95)}ms  mean=${ms(ts.mean)}ms  (scrub+blur; blurJobs=0 here so ~= scrub)`
            )
            console.log(
                `Rust total   p50=${ms(rt.p50)}ms  p95=${ms(rt.p95)}ms  mean=${ms(rt.mean)}ms  (stringify+scrub+parse)`
            )
            console.log(
                `Rust phases  stringify p50=${ms(rStr.p50)}ms  scrub p50=${ms(rScrub.p50)}ms  parse p50=${ms(rParse.p50)}ms`
            )
            console.log(`speedup  end-to-end (TS total / Rust total) = ${(ts.p50 / rt.p50).toFixed(2)}x`)
            console.log(
                `speedup  scrub-only  (TS total / Rust scrub) = ${(ts.p50 / rScrub.p50).toFixed(2)}x   <- the off-event-loop win`
            )
            console.log(
                `throughput  TS ${(1000 / ts.p50).toFixed(1)} msg/s/core   Rust ${(1000 / rt.p50).toFixed(1)} msg/s/core (1 core)`
            )
        }
    }, 300000)
})
