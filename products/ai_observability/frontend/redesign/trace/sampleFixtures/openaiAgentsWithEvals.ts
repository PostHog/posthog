import type { TraceNodeApi } from '../../../generated/api.schemas'
import { EvalResult, NodeProperties, ThreadMessage } from '../types'
import { SampleNodeDetail, SampleTraceFixture, sampleStats } from './sampleTraceFixture'

const TRACE_ID = 'trace_5gL08JNGqLvX2XcwWRWBmJgj6s6VwJcE'
const AGENT_SPAN_ID = 'span_xCcAWaoMGK3OoppmlOJIXhhd'
const PLAN_GENERATION_ID = 'span_FYJ2pRLptL4UCIwPXGLln0GK'
const TOOL_SPAN_ID = 'span_CULdQjgMziv9EbJnburSgu3D'
const ANSWER_GENERATION_ID = 'span_ctqufTsp1mJkbrbkhXzicEWV'
const EVALUATION_ID = 'cbf8ebc8-3e71-746e-5386-1e791507a148'

const TRACE_TIMESTAMP = '2026-09-24T10:18:24.262Z'
const ANSWER_TIMESTAMP = '2026-09-24T10:18:30.258Z'
const AGENT_TIMESTAMP = '2026-09-24T10:18:30.259Z'

const MODEL = 'gpt-5.6-luna'
const GENERATION_NAME = `${MODEL} (openai)`

const USER_REQUEST =
    "Can you check if there are family rooms available in Lisbon for the last week of October, and let me know if I'll need a visa?\nWe're a family of 4, flying from Toronto."

const SEARCH_RESULTS = `Search results for: Lisbon, check-in 2026-10-24, check-out 2026-10-31, guests: 2 adults + 2 children
Filters applied: family room required, free cancellation, max distance 6 km from center

1. Hotel Alfama Vista
   Rating: 4.6/5 (1204 reviews)
   Family room: Yes, sleeps 4, 32 sqm
   Price: EUR 189/night (7 nights: EUR 1323)
   Cancellation: Free until 48h before check-in
   Distance to center: 0.8 km
   Amenities: Rooftop pool, breakfast included, pet friendly

2. Baixa Riverside Suites
   Rating: 4.4/5 (876 reviews)
   Family room: Yes, sleeps 4, 28 sqm
   Price: EUR 165/night (7 nights: EUR 1155)
   Cancellation: Free until 48h before check-in
   Distance to center: 0.4 km
   Amenities: River view, kitchenette, no breakfast

3. Belem Garden Hotel
   Rating: 4.7/5 (592 reviews)
   Family room: Yes, sleeps 4, 35 sqm
   Price: EUR 210/night (7 nights: EUR 1470)
   Cancellation: Free until 48h before check-in
   Distance to center: 3.1 km
   Amenities: Garden courtyard, spa, breakfast included

Visa note: Canadian passport holders do not require a visa for stays under 90 days in Portugal (Schengen area).
Currency: EUR. Card payment accepted at all listed properties.
Availability last checked: 2026-09-24 10:18 UTC. Prices may change if booked more than 48 hours from now.`

const FINAL_ANSWER =
    '{"summary": "Found three family-friendly hotels in Lisbon with rooms for late October, and Canadian passport holders don\'t need a visa for this trip.", "details": {"type": "text", "content": "# Lisbon Family Trip, Oct 24-31\\n\\n## Visa\\nCanadian passport holders do not need a visa for stays under 90 days in Portugal, since it\'s in the Schengen area. Just make sure your passport is valid at least 3 months past your return date. Bring a printed copy of your return flight in case border control asks.\\n\\n## Recommended hotels (family room, sleeps 4)\\n\\n**1. Hotel Alfama Vista** - EUR 189/night, EUR 1,323 total\\n- Rooftop pool, breakfast included, pet friendly\\n- 0.8 km from the center, rated 4.6/5, 1,204 reviews\\n\\n**2. Baixa Riverside Suites** - EUR 165/night, EUR 1,155 total\\n- River view, kitchenette, no breakfast\\n- 0.4 km from the center, rated 4.4/5, 876 reviews\\n\\n**3. Belem Garden Hotel** - EUR 210/night, EUR 1,470 total\\n- Garden courtyard, spa, breakfast included\\n- 3.1 km from the center, rated 4.7/5, 592 reviews\\n\\nAll three have free cancellation until 48 hours before check-in, so you can book now and adjust later if plans shift."}}'

function userRequest(sourceNodeId: string): ThreadMessage {
    return {
        id: `${sourceNodeId}-in-0`,
        role: 'user',
        parts: [{ kind: 'text', text: USER_REQUEST }],
        isInternal: false,
        sourceNodeId,
    }
}

const planInput: ThreadMessage[] = [userRequest(PLAN_GENERATION_ID)]

const planOutput: ThreadMessage[] = [
    {
        id: `${PLAN_GENERATION_ID}-out-1`,
        role: 'assistant',
        parts: [{ kind: 'toolCall', name: 'search_hotels', args: {} }],
        isInternal: true,
        sourceNodeId: PLAN_GENERATION_ID,
    },
]

const answerInput: ThreadMessage[] = [
    userRequest(ANSWER_GENERATION_ID),
    {
        id: `${ANSWER_GENERATION_ID}-in-2`,
        role: 'assistant',
        parts: [{ kind: 'toolCall', name: 'search_hotels', args: {}, result: SEARCH_RESULTS }],
        isInternal: true,
        sourceNodeId: ANSWER_GENERATION_ID,
    },
]

const answerOutput: ThreadMessage[] = [
    {
        id: `${ANSWER_GENERATION_ID}-out-1`,
        role: 'assistant',
        parts: [{ kind: 'text', text: FINAL_ANSWER }],
        isInternal: false,
        sourceNodeId: ANSWER_GENERATION_ID,
    },
]

const EVALUATION_HREF = `/evaluations/${EVALUATION_ID}`

function evalRun(runId: string, timestamp: string, reasoning: string): EvalResult {
    return {
        id: `${EVALUATION_ID}-${runId}`,
        name: 'no_fabrication',
        href: EVALUATION_HREF,
        outcome: 'pass',
        label: 'True',
        reasoning,
        timestamp,
        isBackfill: false,
        target: null,
    }
}

const planEval = evalRun(
    '2864bb23-1838-757a-f65e-83f2826cbbc2',
    '2026-09-24T10:18:41.508Z',
    'The tool call result matches the cited hotel data exactly.'
)

const answerEval = evalRun(
    '65ed9ea6-398b-7c59-32bc-a32577820244',
    '2026-09-24T10:18:44.917Z',
    'The final answer only cites facts present in the tool output.'
)

const answerHelpfulness: EvalResult = {
    id: 'b7d31f02-6a4e-4c19-9e58-0f2c7a91d3e6',
    name: 'helpfulness',
    href: '/evaluations/b7d31f02-6a4e-4c19-9e58-0f2c7a91d3e6',
    outcome: 'unrated',
    label: '0.9',
    reasoning: 'Covers both hotels and the visa question, with prices and cancellation terms.',
    timestamp: '2026-09-20T03:02:11.000Z',
    isBackfill: true,
    target: null,
}

export const openaiAgentsEvals: EvalResult[] = [planEval, answerEval, answerHelpfulness]

const traceEvals: EvalResult[] = [
    { ...planEval, target: { label: GENERATION_NAME, nodeId: PLAN_GENERATION_ID } },
    { ...answerEval, target: { label: GENERATION_NAME, nodeId: ANSWER_GENERATION_ID } },
    { ...answerHelpfulness, target: { label: GENERATION_NAME, nodeId: ANSWER_GENERATION_ID } },
]

const planStats = sampleStats({ costUsd: 0.0016, inputTokens: 853, outputTokens: 49, latencyMs: 2376 })
const answerStats = sampleStats({ costUsd: 0.0079, inputTokens: 1616, outputTokens: 586, latencyMs: 5995 })
const runTotals = { costUsd: 0.0094, inputTokens: 2469, outputTokens: 635 }

const tree: TraceNodeApi[] = [
    {
        id: TRACE_ID,
        kind: 'trace',
        name: 'Trip Planning',
        model: null,
        stats: sampleStats({ ...runTotals, latencyMs: 8377 }),
        hasError: false,
        children: [
            {
                id: AGENT_SPAN_ID,
                kind: 'span',
                name: 'trip-concierge-agent-run',
                model: null,
                stats: sampleStats({ ...runTotals, latencyMs: 8374 }),
                hasError: false,
                children: [
                    {
                        id: PLAN_GENERATION_ID,
                        kind: 'generation',
                        name: GENERATION_NAME,
                        model: MODEL,
                        stats: planStats,
                        hasError: false,
                        children: [],
                    },
                    {
                        id: TOOL_SPAN_ID,
                        kind: 'span',
                        name: 'search_hotels',
                        model: null,
                        stats: sampleStats({}),
                        hasError: false,
                        children: [],
                    },
                    {
                        id: ANSWER_GENERATION_ID,
                        kind: 'generation',
                        name: GENERATION_NAME,
                        model: MODEL,
                        stats: answerStats,
                        hasError: false,
                        children: [],
                    },
                ],
            },
        ],
    },
]

const traceProperties: NodeProperties = {
    timestamp: TRACE_TIMESTAMP,
    provider: null,
    temperature: null,
    sessionId: null,
    promptName: null,
    promptVersion: null,
    person: 'user-1',
}

const sharedRawProperties: Record<string, unknown> = {
    $ai_trace_id: TRACE_ID,
    $ai_parent_id: AGENT_SPAN_ID,
    $ai_framework: 'openai-agents',
    $ai_provider: 'openai',
    $ai_lib: 'posthog-ai',
    $ai_lib_version: '8.3.0',
    feature: 'trip_concierge_agent',
}

function generationDetail(
    id: string,
    timestamp: string,
    input: ThreadMessage[],
    output: ThreadMessage[],
    evalResults: EvalResult[],
    rawProperties: Record<string, unknown>
): SampleNodeDetail {
    return {
        content: { kind: 'messages', input, output },
        error: null,
        properties: { ...traceProperties, timestamp, provider: 'openai' },
        evals: { status: 'ready', results: evalResults },
        raw: {
            event: '$ai_generation',
            id,
            createdAt: timestamp,
            properties: { ...sharedRawProperties, $ai_span_id: id, $ai_model: MODEL, ...rawProperties },
        },
    }
}

export const openaiAgentsWithEvals: SampleTraceFixture = {
    header: {
        name: 'Trip Planning',
        hasError: false,
        olderHref: '/older',
        newerHref: '/newer',
        backLink: { label: 'Back to traces', href: '/traces' },
    },
    summary: {
        traceId: TRACE_ID,
        timestamp: TRACE_TIMESTAMP,
        person: { label: 'user-1', href: '/person/user-1' },
        totals: tree[0].stats,
    },
    tree,
    initialNodeId: ANSWER_GENERATION_ID,
    details: {
        [TRACE_ID]: {
            content: { kind: 'io', input: null, output: null },
            error: null,
            properties: traceProperties,
            evals: { status: 'ready', results: traceEvals },
            raw: {
                id: TRACE_ID,
                createdAt: TRACE_TIMESTAMP,
                traceName: 'Trip Planning',
                totalLatency: 8.377000093460083,
                traceMetadata: { userId: '9432f4d0-1a38-7c4a-a840-a22446331b7d' },
            },
        },
        [AGENT_SPAN_ID]: {
            content: { kind: 'io', input: null, output: null },
            error: null,
            properties: { ...traceProperties, timestamp: AGENT_TIMESTAMP },
            evals: { status: 'ready', results: [] },
            raw: {
                event: '$ai_span',
                id: AGENT_SPAN_ID,
                createdAt: AGENT_TIMESTAMP,
                properties: {
                    ...sharedRawProperties,
                    $ai_span_id: AGENT_SPAN_ID,
                    $ai_parent_id: null,
                    $ai_span_name: 'trip-concierge-agent-run',
                    $ai_span_type: 'agent',
                    $ai_latency: 8.374000072479248,
                    $ai_agent_output_type: 'ZodOutput',
                    $ai_agent_handoffs: ['ItineraryAgent'],
                    $ai_agent_tools: [
                        'search_flights',
                        'check_visa_requirements',
                        'get_weather_forecast',
                        'search_hotels',
                        'convert_currency',
                    ],
                },
            },
        },
        [PLAN_GENERATION_ID]: generationDetail(PLAN_GENERATION_ID, TRACE_TIMESTAMP, planInput, planOutput, [planEval], {
            $ai_response_id: 'resp_t6UzdDRX3JALmEQgkpmbjNstpSizyPOtAY3iwM7txHDAbsznsI',
            $ai_input_tokens: 853,
            $ai_output_tokens: 49,
            $ai_latency: 2.376000165939331,
            $ai_tools_called: 'search_hotels',
            $ai_tool_call_count: 1,
        }),
        [TOOL_SPAN_ID]: {
            content: { kind: 'io', input: '{}', output: SEARCH_RESULTS },
            error: null,
            properties: traceProperties,
            evals: { status: 'ready', results: [] },
            raw: {
                event: '$ai_span',
                id: TOOL_SPAN_ID,
                createdAt: TRACE_TIMESTAMP,
                properties: {
                    ...sharedRawProperties,
                    $ai_span_id: TOOL_SPAN_ID,
                    $ai_span_name: 'search_hotels',
                    $ai_span_type: 'tool',
                    $ai_latency: 0,
                    $ai_input_state: '{}',
                },
            },
        },
        [ANSWER_GENERATION_ID]: generationDetail(
            ANSWER_GENERATION_ID,
            ANSWER_TIMESTAMP,
            answerInput,
            answerOutput,
            [answerEval, answerHelpfulness],
            {
                $ai_response_id: 'resp_klx2gvAQZnLtNaXUgbFxg2L7Az15GoJGFMNBt6s847mQpP4v54',
                $ai_input_tokens: 1616,
                $ai_output_tokens: 586,
                $ai_latency: 5.995000123977661,
            }
        ),
    },
    thread: {
        status: 'ready',
        turns: [
            {
                id: TRACE_ID,
                timestamp: TRACE_TIMESTAMP,
                messages: [...answerInput, ...answerOutput],
                error: null,
            },
        ],
        activeTurnId: TRACE_ID,
    },
    timeline: {
        rows: [
            {
                id: AGENT_SPAN_ID,
                kind: 'span',
                name: 'trip-concierge-agent-run',
                depth: 0,
                startMs: 0,
                durationMs: 8374,
                hasError: false,
            },
            {
                id: PLAN_GENERATION_ID,
                kind: 'generation',
                name: MODEL,
                depth: 1,
                startMs: 1,
                durationMs: 2376,
                hasError: false,
            },
            {
                id: TOOL_SPAN_ID,
                kind: 'span',
                name: 'search_hotels',
                depth: 1,
                startMs: 2377,
                durationMs: null,
                hasError: false,
            },
            {
                id: ANSWER_GENERATION_ID,
                kind: 'generation',
                name: MODEL,
                depth: 1,
                startMs: 2378,
                durationMs: 5995,
                hasError: false,
            },
        ],
        totalMs: 8374,
    },
}
