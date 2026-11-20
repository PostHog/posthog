import { ReactNode } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { tryJsonParse } from 'lib/utils/json'

interface MCPEventViewProps {
    properties: Record<string, any>
}

function Field({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <>
            <dt className="text-secondary text-xs font-medium uppercase tracking-wide pt-0.5">{label}</dt>
            <dd className="m-0 min-w-0 break-words text-sm">{children}</dd>
        </>
    )
}

// SDKs send the payload as an object or as a JSON string, so both print as indented JSON.
function formatPayload(value: unknown): { text: string; language: Language } {
    const parsed = typeof value === 'string' ? tryJsonParse(value, value) : value
    return typeof parsed === 'string'
        ? { text: parsed, language: Language.Text }
        : { text: JSON.stringify(parsed, null, 2), language: Language.JSON }
}

function Payload({ label, value }: { label: string; value: unknown }): JSX.Element {
    const { text, language } = formatPayload(value)
    return (
        <Field label={label}>
            <CodeSnippet language={language} compact wrap thing={label.toLowerCase()} maxLinesWithoutExpansion={12}>
                {text}
            </CodeSnippet>
        </Field>
    )
}

function withSource(label: string, source: unknown): string {
    return source ? `${label} (${String(source).replace(/_/g, ' ')})` : label
}

/** The fields that say what an MCP call was and how it went. */
export function MCPEventView({ properties }: MCPEventViewProps): JSX.Element {
    // Accept both `$mcp_*` and the older un-prefixed `mcp_*` form.
    const get = (key: string): unknown => properties[`$mcp_${key}`] ?? properties[`mcp_${key}`]

    const toolName = get('tool_name')
    const resourceName = get('resource_name')
    const rawIsError = get('is_error')
    // Ingestion can flatten booleans to strings, and "false" is truthy in JS.
    const isError = rawIsError === true || rawIsError === 'true'
    const durationMs = get('duration_ms')
    const intent = get('intent')
    const parameters = get('parameters')
    const response = get('response')

    return (
        <dl className="mx-3 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-6 gap-y-2.5">
            {rawIsError !== undefined && rawIsError !== null ? (
                <Field label="Status">
                    <LemonTag type={isError ? 'danger' : 'success'}>{isError ? 'Error' : 'Success'}</LemonTag>
                </Field>
            ) : null}
            {toolName !== undefined ? (
                <Field label="Tool">
                    <span className="font-mono font-semibold">{String(toolName)}</span>
                </Field>
            ) : resourceName !== undefined ? (
                <Field label="Resource">
                    <span className="font-mono font-semibold">{String(resourceName)}</span>
                </Field>
            ) : null}
            {isError && get('error_message') ? (
                <Field label="Error">
                    <span className="text-danger font-mono text-xs">{String(get('error_message'))}</span>
                </Field>
            ) : null}
            {durationMs !== undefined && durationMs !== null ? (
                <Field label="Duration">{String(durationMs)} ms</Field>
            ) : null}
            {get('interface') ? <Field label="Interface">{String(get('interface'))}</Field> : null}
            {get('client_name') ? <Field label="Client">{String(get('client_name'))}</Field> : null}
            {get('llm_model') ? (
                <Field label={withSource('Model', get('llm_model_source'))}>{String(get('llm_model'))}</Field>
            ) : null}
            {get('server_name') ? <Field label="Server">{String(get('server_name'))}</Field> : null}
            {intent ? (
                <Field label={withSource('Intent', get('intent_source'))}>
                    <span className="whitespace-pre-wrap">{String(intent)}</span>
                </Field>
            ) : null}
            {parameters !== undefined && parameters !== null ? <Payload label="Parameters" value={parameters} /> : null}
            {response !== undefined && response !== null ? <Payload label="Response" value={response} /> : null}
        </dl>
    )
}
