import type { TraceNodeApi } from '../../../generated/api.schemas'
import { MessagePart, NodeProperties, ThreadMessage } from '../types'
import { SampleTraceFixture, sampleStats } from './sampleTraceFixture'

const TRACE_ID = '3030b60b-110e-7653-675c-235b05cc9a77'
const SPAN_ID = '03aaa1fa-517a-779b-ae4d-3bc682a08ab2'
const GENERATION_ID = 'a18285a8-8cef-7877-ec78-ad8c9a72eb0a'
const TIMESTAMP = '2026-09-03T14:02:11.000Z'
const SPAN_TIMESTAMP = '2026-09-03T14:02:11.001Z'

const ERROR_MESSAGE =
    "Error code: 400 - {'message': \"The model 'llama3.1-70b' does not support image inputs. Remove the image_url content block from the message and resend the request, or switch to a model that supports vision.\", 'type': 'invalid_request_error', 'param': 'messages', 'code': 'unsupported_content_type'}"

const SYSTEM_PROMPT = `You are a warehouse intake assistant that extracts structured information from photographs of shipping labels and package markings.

Your job is to look at the attached image and call the extract_package_label_details function with every field you can confidently read from the label. Never guess a value you cannot see clearly; leave it null instead of inventing one.

## Fields

- brand: the printed brand or manufacturer wordmark on the label, if visible.
- name: the product or item name as printed on the label.
- quantity: the unit count in the shipment, as an integer if printed.
- estimated_weight_kg: the package weight in kilograms. Convert from pounds if the label prints lbs instead.
- package_size_tier_code: one of the enumerated size tiers printed or implied by the carton dimensions.
- metadata: any other key-value pairs printed on the label, such as barcodes, lot codes, or hazard symbols, that don't fit another field.
- manufacturer: the manufacturing company name, which may differ from the brand on the front of the box.
- country_of_manufacture: the country printed after "Made in" or an equivalent phrase.
- expiration_date: the expiry or best-before date, normalized to ISO 8601.

## Rules

1. Read every visible line of text on the label before answering, including small print near the barcode.
2. When two candidate values conflict, prefer the clearest and most complete printed value.
3. Do not translate text; keep the original spelling and capitalization from the label.
4. If the image is too blurry or the label is torn in a way that hides a field, leave that field null rather than guessing.`

const LABEL_PHOTO: MessagePart = {
    kind: 'attachment',
    mediaType: 'image',
    name: null,
    mimeType: 'image/jpeg',
    url: 'data:image/jpeg;base64,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',
}

function labelMessages(sourceNodeId: string): ThreadMessage[] {
    return [
        {
            id: `${sourceNodeId}-in-0`,
            role: 'system',
            parts: [{ kind: 'text', text: SYSTEM_PROMPT }],
            isInternal: false,
            sourceNodeId,
        },
        {
            id: `${sourceNodeId}-in-1`,
            role: 'user',
            parts: [LABEL_PHOTO],
            isInternal: false,
            sourceNodeId,
        },
    ]
}

export const cerebrasLabelMessages: ThreadMessage[] = labelMessages(GENERATION_ID)

const tree: TraceNodeApi[] = [
    {
        id: TRACE_ID,
        kind: 'trace',
        name: 'scan_package',
        model: null,
        stats: sampleStats({ latencyMs: 2133 }),
        hasError: true,
        children: [
            {
                id: SPAN_ID,
                kind: 'span',
                name: 'RunnableSequence',
                model: null,
                stats: sampleStats({ latencyMs: 2008 }),
                hasError: true,
                children: [
                    {
                        id: GENERATION_ID,
                        kind: 'generation',
                        name: 'extract_shipping_label_fields_llm',
                        model: 'qwen-3.8-27b',
                        stats: sampleStats({ latencyMs: 2004 }),
                        hasError: true,
                        children: [],
                    },
                ],
            },
        ],
    },
]

const traceProperties: NodeProperties = {
    timestamp: TIMESTAMP,
    provider: null,
    temperature: null,
    sessionId: TRACE_ID,
    promptName: null,
    promptVersion: null,
    person: 'user-1',
}

const sharedRawProperties: Record<string, unknown> = {
    $ai_trace_id: TRACE_ID,
    $ai_session_id: TRACE_ID,
    $ai_framework: 'langchain',
    $ai_is_error: true,
    $ai_error: ERROR_MESSAGE,
    $lib: 'posthog-python',
    $lib_version: '7.44.2',
    $python_version: '3.12.14',
    $os: 'Linux',
}

export const langchainCerebrasImageError: SampleTraceFixture = {
    header: {
        name: 'scan_package',
        hasError: true,
        olderHref: '/older',
        newerHref: '/newer',
        backLink: { label: 'Back to traces', href: '/traces' },
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
            raw: { id: TRACE_ID, createdAt: TIMESTAMP, traceName: 'scan_package', totalLatency: 2.133077383041382 },
        },
        [SPAN_ID]: {
            content: { kind: 'messages', input: labelMessages(SPAN_ID), output: [] },
            error: ERROR_MESSAGE,
            properties: { ...traceProperties, timestamp: SPAN_TIMESTAMP },
            evals: { status: 'ready', results: [] },
            raw: {
                event: '$ai_span',
                id: SPAN_ID,
                createdAt: SPAN_TIMESTAMP,
                properties: {
                    ...sharedRawProperties,
                    $ai_span_id: SPAN_ID,
                    $ai_parent_id: TRACE_ID,
                    $ai_span_name: 'RunnableSequence',
                    $ai_latency: 2.0081095695495605,
                },
            },
        },
        [GENERATION_ID]: {
            content: { kind: 'messages', input: cerebrasLabelMessages, output: [] },
            error: ERROR_MESSAGE,
            properties: { ...traceProperties, provider: 'cerebras', temperature: 0 },
            evals: { status: 'ready', results: [] },
            raw: {
                event: '$ai_generation',
                id: GENERATION_ID,
                createdAt: TIMESTAMP,
                properties: {
                    ...sharedRawProperties,
                    $ai_span_id: GENERATION_ID,
                    $ai_parent_id: SPAN_ID,
                    $ai_span_name: 'extract_shipping_label_fields_llm',
                    $ai_provider: 'cerebras',
                    $ai_model: 'qwen-3.8-27b',
                    $ai_model_parameters: { max_tokens: 2048, stream: false, temperature: 0 },
                    $ai_http_status: 400,
                    $ai_latency: 2.0036303997039795,
                },
            },
        },
    },
    thread: {
        status: 'ready',
        turns: [{ id: TRACE_ID, timestamp: TIMESTAMP, messages: cerebrasLabelMessages, error: ERROR_MESSAGE }],
        activeTurnId: TRACE_ID,
    },
    timeline: {
        rows: [
            {
                id: SPAN_ID,
                kind: 'span',
                name: 'RunnableSequence',
                depth: 0,
                startMs: 0,
                durationMs: 2008,
                hasError: true,
            },
            {
                id: GENERATION_ID,
                kind: 'generation',
                name: 'extract_shipping_label_fields_llm',
                depth: 1,
                startMs: 3,
                durationMs: 2004,
                hasError: true,
            },
        ],
        totalMs: 2008,
    },
}
