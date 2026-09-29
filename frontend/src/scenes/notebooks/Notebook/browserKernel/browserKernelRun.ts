import { performQuery } from '~/queries/query'
import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import type { NotebookBrowserRunPlanResponseApi } from 'products/notebooks/frontend/generated/api.schemas'

import type { BrowserKernelClient } from './BrowserKernelClient'
import type {
    BrowserKernelEnvelope,
    BrowserKernelInput,
    BrowserKernelRunPayload,
    BrowserKernelStagedInput,
} from './browserKernelProtocol'

// A recorded envelope is stored whole in Postgres. Figures are what grows it, so over this size
// they stay in the tab and only the table and text reach the record.
const MAX_RECORDED_ENVELOPE_CHARS = 4_000_000

/** Rows of one upstream SQL result, in the column-major shape the kernel loads fastest. */
export async function fetchBrowserInputRows(key: string, query: string): Promise<BrowserKernelStagedInput> {
    const response = await performQuery<HogQLQuery>({ kind: NodeKind.HogQLQuery, query }, undefined, 'async')
    const columns: string[] = (response.columns ?? []).map(String)
    const types = ((response.types ?? []) as unknown[][]).map(
        ([name, type]) => [String(name), String(type)] as [string, string]
    )
    const rows = (response.results ?? []) as unknown[][]
    const values = columns.map((_, index) => rows.map((row) => row[index] ?? null))
    return { key, columns, types, values }
}

/** Load the upstream rows a run reads, skipping any the kernel already holds from the same run. */
export async function stageBrowserInputs(
    client: BrowserKernelClient,
    inputs: NotebookBrowserRunPlanResponseApi['inputs'],
    fetchRows: (key: string, query: string) => Promise<BrowserKernelStagedInput> = fetchBrowserInputRows
): Promise<{ payloadInputs: BrowserKernelInput[]; staged: BrowserKernelStagedInput[] }> {
    const payloadInputs: BrowserKernelInput[] = []
    const staged: BrowserKernelStagedInput[] = []
    for (const input of inputs) {
        if (input.kind !== 'hogql') {
            payloadInputs.push({ name: input.name, kind: 'local' })
            continue
        }
        const key = input.key ?? ''
        payloadInputs.push({ name: input.name, kind: 'hogql', node_id: input.node_id ?? '', key })
        if (!(await client.hasInput(key)) && !staged.some((item) => item.key === key)) {
            staged.push(await fetchRows(key, input.query ?? ''))
        }
    }
    return { payloadInputs, staged }
}

export function browserRunPayload(
    nodeId: string,
    plan: NotebookBrowserRunPlanResponseApi,
    outputName: string,
    inputs: BrowserKernelInput[]
): BrowserKernelRunPayload {
    return {
        node_id: nodeId,
        node_type: plan.node_type === 'duckdb' ? 'duckdb' : 'python',
        code: plan.code,
        output_name: outputName,
        inputs,
        variables: plan.variables,
    }
}

/** The envelope as the backend records it: no kernel-only fields, and figures only while they fit. */
export function recordableEnvelope(envelope: BrowserKernelEnvelope): Omit<BrowserKernelEnvelope, 'frames'> {
    const { frames: _frames, result_id: _resultId, ...rest } = envelope
    if (JSON.stringify(rest).length <= MAX_RECORDED_ENVELOPE_CHARS) {
        return rest
    }
    return {
        ...rest,
        media: [],
        stderr: `${rest.stderr ?? ''}\n[figures were not saved with the notebook: over the size limit]`.trimStart(),
    }
}
