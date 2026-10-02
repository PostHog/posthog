import type { NotebookKernelFrame } from '../notebookKernelInfoLogic'

// Pinned so the script and every package wheel come from one immutable release. The CSP in
// posthog/csp_middleware.py names this exact path, so a version bump must update both.
export const PYODIDE_VERSION = '314.0.7'
export const PYODIDE_INDEX_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`

// Loaded at startup because every run needs them: DuckDB for SQL over local frames, pandas for
// the frames themselves. Anything else a cell imports loads on first use.
export const BROWSER_KERNEL_PRELOADED_PACKAGES = ['pandas', 'duckdb', 'micropip']

export type BrowserKernelFrame = NotebookKernelFrame & {
    node_id?: string | null
    origin?: 'input' | 'output'
}

export type BrowserKernelInput =
    | { name: string; kind: 'local' }
    | {
          name: string
          kind: 'hogql'
          node_id: string
          key: string
      }

export type BrowserKernelRunPayload = {
    node_id: string
    node_type: 'python' | 'duckdb'
    code: string
    output_name: string
    inputs: BrowserKernelInput[]
    variables?: Record<string, unknown>
    page_limit?: number
}

export type BrowserKernelEnvelope = {
    status: 'ok' | 'error' | 'interrupted'
    error?: string
    stdout?: string
    stderr?: string
    columns: string[]
    types: [string, string][]
    row_count: number
    first_page: (string | number | null)[][]
    has_more: boolean
    media?: { mime_type: string; data: string }[]
    result_id?: string
    frames?: BrowserKernelFrame[] | null
}

export type BrowserKernelPage = {
    columns: string[]
    types: [string, string][]
    rows: (string | number | null)[][]
    has_more: boolean
    total: number
}

export type BrowserKernelFramePage = {
    name: string
    columns: { name: string; type: string }[]
    rows: unknown[][]
    totalRowCount: number
    includedRowCount: number
    offset: number
    nextOffset: number | null
    truncated: boolean
}

export type BrowserKernelStagedInput = {
    key: string
    columns: string[]
    types: [string, string][]
    /** Column-major values, which cross into Python far faster than row objects. */
    values: unknown[][]
}

export type BrowserKernelRequest =
    | { type: 'init'; id: number; indexURL: string; packages: string[]; interruptBuffer: SharedArrayBuffer | null }
    | { type: 'run'; id: number; payload: BrowserKernelRunPayload; staged: BrowserKernelStagedInput[] }
    | { type: 'hasInput'; id: number; key: string }
    | { type: 'page'; id: number; resultId: string; offset: number; limit: number }
    | { type: 'readFrame'; id: number; name: string; offset: number; limit: number }
    | { type: 'frames'; id: number }

export type BrowserKernelResponse =
    | { type: 'result'; id: number; value: unknown }
    | { type: 'error'; id: number; message: string }
    | { type: 'progress'; message: string }
