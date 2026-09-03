import { Liquid } from 'liquidjs'

import { HogFunctionInvocationGlobalsWithInputs } from '../types'

// Rendering is synchronous on shared multi-tenant workers, so an unbounded template would
// stall or OOM the whole process. These budgets make an over-budget template fail only its own invocation.
const LIQUID_PARSE_LIMIT_CHARS = 100_000
const LIQUID_MEMORY_LIMIT_UNITS = 1_000_000
// Time and output are budgeted per invocation, not per template, because one invocation renders
// every string leaf of every liquid input and those leaves would otherwise each get a full budget.
const LIQUID_RENDER_LIMIT_MS = 500
const LIQUID_OUTPUT_LIMIT_CHARS = 1_000_000

const LIQUID_TAG_CLOSERS: Record<string, string> = { '{': '}}', '%': '%}' }

// These filters evaluate a tenant-written expression once per array item and LiquidJS only checks
// the render deadline between template nodes, so one filter call can run unbounded. They are replaced
// with a throwing filter rather than unregistered, because an unknown filter silently acts as identity.
const LIQUID_UNBOUNDED_FILTERS = ['where_exp', 'find_exp', 'find_index_exp', 'reject_exp', 'group_by_exp']

export class LiquidRenderBudget {
    private usedMs = 0
    private outputChars = 0

    remainingMs(): number {
        return Math.max(0, LIQUID_RENDER_LIMIT_MS - this.usedMs)
    }

    useTime(ms: number): void {
        this.usedMs += ms
    }

    useOutput(chars: number): void {
        this.outputChars += chars
        if (this.outputChars > LIQUID_OUTPUT_LIMIT_CHARS) {
            throw new Error(`liquid output limit exceeded (${LIQUID_OUTPUT_LIMIT_CHARS} characters per invocation)`)
        }
    }
}

const decodeEntities = (tag: string): string => {
    return tag
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#x27;/g, "'")
        .replace(/&amp;/g, '&') // NOTE: This should always be last
}

// TRICKY: Unlayer replaces all liquid's elements like > for example with &gt;
// We need to decode these but _only_ for the liquid elements i.e. content within {{ }} or {% %}
// This is a single forward pass: a regex with a lazy `.*?` rescans to the end of the line for every
// unmatched opener, which is quadratic on tenant-controlled input.
const decodeLiquidTags = (template: string): string => {
    let out = ''
    let cursor = 0
    const exhausted = new Set<string>()

    while (cursor < template.length) {
        const open = template.indexOf('{', cursor)
        if (open === -1) {
            break
        }
        const closer = LIQUID_TAG_CLOSERS[template[open + 1]]
        const close = closer && !exhausted.has(closer) ? template.indexOf(closer, open + 2) : -1
        if (close === -1) {
            if (closer) {
                exhausted.add(closer)
            }
            out += template.slice(cursor, open + 1)
            cursor = open + 1
            continue
        }
        out += template.slice(cursor, open) + decodeEntities(template.slice(open, close + 2))
        cursor = close + 2
    }

    return out + template.slice(cursor)
}

export class LiquidRenderer {
    private static _liquid: Liquid | null = null

    private static get liquid(): Liquid {
        if (!this._liquid) {
            this._liquid = new Liquid({
                outputEscape: 'escape',
                // Render partials from an in-memory map only: this disables LiquidJS's filesystem-backed
                // partial loading, so user-controlled templates can't read local files via include/render/layout.
                templates: {},
                parseLimit: LIQUID_PARSE_LIMIT_CHARS,
                renderLimit: LIQUID_RENDER_LIMIT_MS,
                memoryLimit: LIQUID_MEMORY_LIMIT_UNITS,
            })
            for (const name of LIQUID_UNBOUNDED_FILTERS) {
                this._liquid.registerFilter(name, () => {
                    throw new Error(`liquid filter ${name} is not supported`)
                })
            }
        }
        return this._liquid
    }

    static renderWithHogFunctionGlobals(
        template: string,
        globals: HogFunctionInvocationGlobalsWithInputs,
        budget: LiquidRenderBudget = new LiquidRenderBudget()
    ): string {
        // Checked before decoding so the decoder never sees a string LiquidJS would reject anyway.
        if (template.length > LIQUID_PARSE_LIMIT_CHARS) {
            throw new Error(`liquid parse length limit exceeded (${LIQUID_PARSE_LIMIT_CHARS} characters)`)
        }

        const context = {
            ...globals,
            now: new Date(),
        }

        const start = performance.now()
        try {
            const result: string = this.liquid.parseAndRenderSync(decodeLiquidTags(template), context, {
                renderLimit: budget.remainingMs(),
            })
            // String length is O(1) on a V8 rope, so this rejects a huge result before anything flattens it.
            budget.useOutput(result.length)
            return result
        } finally {
            budget.useTime(performance.now() - start)
        }
    }
}
