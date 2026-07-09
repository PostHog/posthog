/**
 * Exposure-decision coverage. Uses a synthetic catalog sized like a rich server
 * (the real PostHog MCP is ~603 tools / ~2.7M serialized chars) rather than a
 * committed multi-MB fixture.
 */
import type { RemoteMcpTool } from './mcp-clients'
import { DEFAULT_MCP_EXPOSURE_BUDGET, decideMcpExposure, serializedToolChars } from './mcp-tool-budget'

function makeCatalog(count: number, schemaFields: number, descWords: number): RemoteMcpTool[] {
    return Array.from({ length: count }, (_, i) => {
        const properties: Record<string, unknown> = {}
        for (let f = 0; f < schemaFields; f++) {
            properties[`field_${f}`] = { type: 'string', description: `Parameter ${f}. ${'detail '.repeat(6)}`.trim() }
        }
        return {
            name: `tool_${i}`,
            description: `Synthetic tool ${i}. ${'lorem ipsum '.repeat(descWords)}`.trim(),
            inputSchema: { type: 'object', properties },
        }
    })
}

const richCatalog = makeCatalog(600, 50, 6) // ~3M serialized chars
const smallCatalog = makeCatalog(38, 4, 3)

describe('MCP exposure decision', () => {
    it('a rich surface exceeds the budget → proxy', () => {
        const d = decideMcpExposure(richCatalog)
        expect(d.mode).toBe('proxy')
        expect(d.toolCount).toBeGreaterThan(DEFAULT_MCP_EXPOSURE_BUDGET.maxInlineTools)
        expect(d.serializedChars).toBeGreaterThan(DEFAULT_MCP_EXPOSURE_BUDGET.maxInlineChars)
        expect(d.reasons.length).toBe(2)
        expect(d.serializedChars).toBeGreaterThan(2_000_000)
    })

    it('a small surface fits the budget → inline', () => {
        const d = decideMcpExposure(smallCatalog)
        expect(d.mode).toBe('inline')
        expect(d.reasons).toEqual([])
    })

    it('a curated slice of a rich surface stays inline', () => {
        expect(decideMcpExposure(richCatalog.slice(0, 10)).mode).toBe('inline')
    })

    it('proxying collapses the surface to ~constant cost regardless of N', () => {
        const PROXY_BLOCK_CHARS = 2_000
        expect(serializedToolChars(richCatalog)).toBeGreaterThan(50 * PROXY_BLOCK_CHARS)
    })
})
