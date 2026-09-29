import { NodeProperties, ThreadMessage, TraceTreeNode } from '../types'
import { SampleTraceFixture, sampleStats } from './sampleTraceFixture'

const TRACE_ID = '2fa60c6497874ba3c4633d94fdfae64f'
const GENERATION_ID = 'd6263394121a6a51'
const TIMESTAMP = '2026-09-01T12:15:02.000Z'

const DRAFT_ROLLUP_CODE = `function rollupMonthly(card, history, vars) {
  // Sum recurring spend per category, ignore anything under the noise
  // floor, and flag categories that grew more than 20% month over month.
  const NOISE_FLOOR = 50;
  const GROWTH_ALERT = 0.2;
  const buckets = {};

  for (const txn of card.txns) {
    // NOTE: coding is sometimes an empty array for uncategorized imports
    const cat = txn.coding[0].code;
    const amount = txn.n;
    if (amount < NOISE_FLOOR) continue;
    buckets[cat] = (buckets[cat] || 0) + amount;
  }

  const flagged = [];
  for (const cat in buckets) {
    const prior = history.find((h) => h.txt.includes(cat));
    if (!prior) continue;
    const delta = (buckets[cat] - prior.n) / prior.n;
    if (delta > GROWTH_ALERT) {
      flagged.push({ category: cat, delta, current: buckets[cat] });
    }
  }

  return { buckets, flagged, asOf: card.due };
}
`

const FIXED_ROLLUP_CODE = `function rollupMonthly(card, history, vars) {
  const buckets = {};
  for (const txn of card.txns) {
    const cat = txn.coding?.[0]?.code ?? "uncategorized";
    if (txn.n < 50) continue;
    buckets[cat] = (buckets[cat] || 0) + txn.n;
  }
  return { buckets, asOf: card.due };
}
`

const LINKED_CARDS_RESULT =
    '{"profile": {"name": [{"family": "Warner", "given": ["Sophia"]}], "birthDate": "1986-09-23", "gender": "female", "address": [{"state": "CA"}], "identifier": ["cust-warner-sophia-88213045-w2"], "aliases": []}, "txns": [{"txt": "Recurring grocery charge flagged for manual review", "code": {"coding": [{"code": "grocery-recurring-monthly-04", "display": "Grocery, recurring", "version": "1"}]}, "issued": "2026-07-30T17:32:32.010Z", "due": "2026-07-27T14:27:19.000Z", "n": 89, "status": "fresh", "tags": ["needs-review-flag"]}], "notes": [], "history": [{"txt": "Matched recurring grocery debit to budget category rule", "recorded": "2026-07-13T22:42:45.723Z", "status": "completed", "attempts": 11}, {"txt": "Matched recurring rent debit to budget category rule set", "recorded": "2026-07-13T22:41:36.164Z", "status": "completed", "attempts": 6}], "flags": [], "vars": [{"k": "rent-0F5c1cd", "dep": [], "n": 1}, {"k": "grocery-754a6", "dep": [], "n": 14}, {"k": "savings-2D218597", "dep": ["budget-total-aE164", "category-e2349f"], "n": 20}], "revisions": []}'

const input: ThreadMessage[] = [
    {
        id: `${GENERATION_ID}-in-0`,
        role: 'user',
        parts: [
            {
                kind: 'text',
                text: "Hey, can you take another look at the Monthly Rollup card? It's supposed to sum\nrecurring transactions per category, skip anything under $50, and flag categories\nthat jumped more than 20% versus last month. Right now it's throwing an error on\nthe grocery bucket and I can't tell why. Pull the linked cards if you need context.",
            },
        ],
        isInternal: false,
        sourceNodeId: GENERATION_ID,
    },
    {
        id: `${GENERATION_ID}-in-1`,
        role: 'assistant',
        parts: [
            {
                kind: 'thinking',
                text: "I should pull the linked cards\nand variable history first to see\nwhat's actually stored here.",
            },
            {
                kind: 'toolCall',
                name: 'calc',
                args: { code: DRAFT_ROLLUP_CODE, v: 'card_6PbgqloIxg@rollup-draft' },
                result: LINKED_CARDS_RESULT,
            },
        ],
        isInternal: true,
        sourceNodeId: GENERATION_ID,
    },
]

const output: ThreadMessage[] = [
    {
        id: `${GENERATION_ID}-out-0`,
        role: 'assistant',
        parts: [
            {
                kind: 'toolCall',
                name: 'calc',
                args: { v: 'card_6PbgqloIxg@rollup-fixed-guarded-v2', code: FIXED_ROLLUP_CODE },
            },
        ],
        isInternal: true,
        sourceNodeId: GENERATION_ID,
    },
]

export const anthropicThinkingMessages: ThreadMessage[] = [...input, ...output]

const generationStats = sampleStats({
    costUsd: 0.0435,
    inputTokens: 2,
    outputTokens: 218,
    cacheReadTokens: 56210,
    latencyMs: 3539,
})

const tree: TraceTreeNode[] = [
    {
        id: TRACE_ID,
        kind: 'trace',
        name: 'run-budget-rollup',
        model: null,
        stats: sampleStats({ costUsd: 0.0435, inputTokens: 2, outputTokens: 218, latencyMs: 3539 }),
        hasError: false,
        children: [
            {
                id: GENERATION_ID,
                kind: 'generation',
                name: 'run-budget-rollup',
                model: 'claude-opus-5-5',
                stats: generationStats,
                hasError: false,
                children: [],
            },
        ],
    },
]

const traceProperties: NodeProperties = {
    timestamp: TIMESTAMP,
    provider: null,
    temperature: null,
    sessionId: null,
    promptName: null,
    promptVersion: null,
    person: 'user-1',
}

export const anthropicMessagesThinkingToolUse: SampleTraceFixture = {
    header: {
        name: 'run-budget-rollup',
        hasError: false,
        olderHref: '/older',
        newerHref: '/newer',
        backHref: '/traces',
    },
    summary: {
        traceId: TRACE_ID,
        timestamp: TIMESTAMP,
        person: { label: 'user-1', href: '/person/user-1' },
        totals: tree[0].stats,
    },
    tree,
    initialNodeId: GENERATION_ID,
    details: {
        [TRACE_ID]: {
            content: { kind: 'io', input: null, output: null },
            error: null,
            properties: traceProperties,
            evals: { status: 'ready', results: [] },
            raw: { id: TRACE_ID, createdAt: TIMESTAMP, traceName: 'run-budget-rollup' },
        },
        [GENERATION_ID]: {
            content: { kind: 'messages', input, output },
            error: null,
            properties: { ...traceProperties, provider: 'anthropic.messages' },
            evals: { status: 'ready', results: [] },
            raw: {
                event: '$ai_generation',
                id: GENERATION_ID,
                createdAt: TIMESTAMP,
                properties: {
                    $ai_provider: 'anthropic.messages',
                    $ai_model: 'claude-opus-5-5',
                    $ai_span_name: 'run-budget-rollup',
                    $ai_trace_id: TRACE_ID,
                    $ai_span_id: GENERATION_ID,
                    $ai_lib: 'posthog-ai',
                    $ai_lib_version: '7.21.0',
                    $ai_latency: 3.539117633998394,
                    $ai_input_tokens: 2,
                    $ai_output_tokens: 218,
                    $ai_cache_read_input_tokens: 56210,
                    $ai_cache_creation_input_tokens: 1585,
                    $ai_stop_reason: 'tool_use',
                    $ai_http_status: 200,
                    $ai_tools_called: 'calc',
                    $ai_tool_call_count: 1,
                    resource_locator: 'personal-finance/workbooks/monthly-budget/cards/rollup-final',
                },
            },
        },
    },
    thread: {
        turns: [{ id: TRACE_ID, timestamp: TIMESTAMP, messages: anthropicThinkingMessages, error: null }],
        activeTurnId: TRACE_ID,
    },
    timeline: {
        rows: [
            {
                id: GENERATION_ID,
                kind: 'generation',
                name: 'run-budget-rollup',
                depth: 0,
                startMs: 0,
                durationMs: 3539,
            },
        ],
        totalMs: 3539,
    },
}
