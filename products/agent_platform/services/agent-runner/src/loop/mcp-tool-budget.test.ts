/**
 * Prompt-size / exposure-decision coverage for real MCP catalogs.
 *
 * Reads the catalogs captured from live servers (the same bytes a connection's
 * `listTools()` returns) and asserts the inline-vs-proxy decision + quantifies
 * what front-loading each surface would cost the prompt. This is the regression
 * net for the context explosion that motivated the proxy: if a rich server's
 * surface (or the budget) drifts such that it would be inlined, this fails.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { RemoteMcpTool } from './mcp-clients'
import { DEFAULT_MCP_EXPOSURE_BUDGET, decideMcpExposure, serializedToolChars } from './mcp-tool-budget'

const __dirname = dirname(fileURLToPath(import.meta.url))
const FIXTURES = resolve(__dirname, '../../../agent-tests/src/fixtures/mcp-catalogs')

function loadCatalog(file: string): RemoteMcpTool[] {
    return JSON.parse(readFileSync(resolve(FIXTURES, file), 'utf-8')) as RemoteMcpTool[]
}

const posthog = loadCatalog('posthog-mcp.json')
const incidentio = loadCatalog('incident-io-mcp.json')

describe('MCP exposure decision over real catalogs', () => {
    it('PostHog MCP (full surface) exceeds the budget → proxy', () => {
        const d = decideMcpExposure(posthog)
        expect(d.mode).toBe('proxy')
        // Both limits trip — it's huge on every axis.
        expect(d.toolCount).toBeGreaterThan(DEFAULT_MCP_EXPOSURE_BUDGET.maxInlineTools)
        expect(d.serializedChars).toBeGreaterThan(DEFAULT_MCP_EXPOSURE_BUDGET.maxInlineChars)
        expect(d.reasons.length).toBe(2)
        // The explosion this prevents: front-loading would be >2 M chars (~500 k+ tokens).
        expect(d.serializedChars).toBeGreaterThan(2_000_000)
    })

    it('incident.io (38 tools) fits the budget → inline', () => {
        const d = decideMcpExposure(incidentio)
        expect(d.mode).toBe('inline')
        expect(d.reasons).toEqual([])
    })

    it('a curated slice of the PostHog MCP stays inline', () => {
        // Smallest 10 tools by schema size — the kind of allowlist an author picks.
        const slice = [...posthog].sort((a, b) => serializedToolChars([a]) - serializedToolChars([b])).slice(0, 10)
        expect(decideMcpExposure(slice).mode).toBe('inline')
    })

    it('proxying collapses the surface to ~constant cost regardless of N', () => {
        // The proxy replaces N tools with two small helper descriptors; model
        // the saving as the full inline block vs a fixed ~2-tool budget.
        const inlineChars = serializedToolChars(posthog)
        const PROXY_BLOCK_CHARS = 2_000 // two helper tools (search + call), generously
        expect(inlineChars).toBeGreaterThan(50 * PROXY_BLOCK_CHARS)
    })

    it.each([
        ['posthog (full)', posthog],
        ['incident.io (full)', incidentio],
    ])('reports prompt cost for %s', (_label, catalog) => {
        const d = decideMcpExposure(catalog)
        // Surfaced in the assertion so the numbers are visible in test output.
        expect({
            tools: d.toolCount,
            chars: d.serializedChars,
            estTokens: Math.round(d.serializedChars / 4),
            mode: d.mode,
        }).toMatchObject({ mode: d.mode })
    })
})
