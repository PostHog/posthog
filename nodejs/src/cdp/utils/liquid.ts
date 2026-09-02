import { Liquid } from 'liquidjs'

import { HogFunctionInvocationGlobalsWithInputs } from '../types'

const LIQUID_REGEX = /\{\{(.*?)\}\}|{%(.*?)%}/g

export const LIQUID_RENDER_LIMITS = {
    maxSourceBytes: 100 * 1024,
    maxRenderDurationMs: 500,
    maxMemoryUnits: 4 * 1024 * 1024,
    maxOutputBytes: 4 * 1024 * 1024,
    softRenderDurationMs: 100,
    softOutputBytes: 1024 * 1024,
} as const

export type LiquidResourceLimit = 'source' | 'render' | 'memory' | 'output'

export interface LiquidRenderLimits {
    maxSourceBytes: number
    maxRenderDurationMs: number
    maxMemoryUnits: number
    maxOutputBytes: number
    softRenderDurationMs: number
    softOutputBytes: number
}

export interface LiquidRenderBudgetStats {
    attempted: boolean
    sourceBytes: number
    renderDurationMs: number
    outputBytes: number
    hardLimit?: LiquidResourceLimit
}

const LIQUID_LIMIT_MESSAGES: Record<LiquidResourceLimit, string> = {
    source: 'Liquid template inputs are larger than the 100 KB total limit. Shorten them and try again.',
    render: 'Liquid template took too long to render. Reduce its loops and try again.',
    memory: 'Liquid template used too much memory. Reduce its loops or output and try again.',
    output: 'Liquid template produced too much output. Reduce its output and try again.',
}

export class LiquidTemplateResourceLimitError extends Error {
    constructor(public readonly resource: LiquidResourceLimit) {
        super(LIQUID_LIMIT_MESSAGES[resource])
        this.name = 'LiquidTemplateResourceLimitError'
    }
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
                parseLimit: LIQUID_RENDER_LIMITS.maxSourceBytes,
                renderLimit: LIQUID_RENDER_LIMITS.maxRenderDurationMs,
                memoryLimit: LIQUID_RENDER_LIMITS.maxMemoryUnits,
            })
        }
        return this._liquid
    }

    static renderWithHogFunctionGlobals(
        template: string,
        globals: HogFunctionInvocationGlobalsWithInputs,
        renderLimitMs: number = LIQUID_RENDER_LIMITS.maxRenderDurationMs,
        memoryLimit: number = LIQUID_RENDER_LIMITS.maxMemoryUnits
    ): string {
        const context = {
            ...globals,
            now: new Date(),
        }

        // TRICKY: Unlayer replaces all liquid's elements like > for example with &gt;
        // We need to decode these but _only_ for the liquid elements i.e. content within {{ }} or {% %}
        const decodedTemplate = template.replace(LIQUID_REGEX, (match) => {
            return match
                .replace(/&lt;/g, '<')
                .replace(/&gt;/g, '>')
                .replace(/&quot;/g, '"')
                .replace(/&#x27;/g, "'")
                .replace(/&amp;/g, '&') // NOTE: This should always be last
        })

        return this.liquid.parseAndRenderSync(decodedTemplate, context, {
            renderLimit: renderLimitMs,
            memoryLimit,
        })
    }
}

function liquidLimitFromError(error: unknown): LiquidResourceLimit | null {
    const message = error instanceof Error ? error.message : String(error)
    if (message.includes('parse length limit exceeded')) {
        return 'source'
    }
    if (message.includes('template render limit exceeded')) {
        return 'render'
    }
    if (message.includes('memory alloc limit exceeded')) {
        return 'memory'
    }
    return null
}

export class LiquidRenderBudget {
    private attempted = false
    private sourceBytes = 0
    private renderDurationMs = 0
    private outputBytes = 0
    private hardLimit?: LiquidResourceLimit

    constructor(private readonly limits: LiquidRenderLimits = LIQUID_RENDER_LIMITS) {}

    render(template: string, globals: HogFunctionInvocationGlobalsWithInputs): string {
        this.attempted = true
        this.sourceBytes += Buffer.byteLength(template, 'utf8')
        if (this.sourceBytes > this.limits.maxSourceBytes) {
            this.throwLimit('source')
        }

        const remainingRenderMs = this.limits.maxRenderDurationMs - this.renderDurationMs
        if (remainingRenderMs <= 0) {
            this.throwLimit('render')
        }

        const startedAt = performance.now()
        let result: string
        try {
            result = LiquidRenderer.renderWithHogFunctionGlobals(
                template,
                globals,
                remainingRenderMs,
                this.limits.maxMemoryUnits
            )
        } catch (error) {
            this.renderDurationMs += performance.now() - startedAt
            const resource = liquidLimitFromError(error)
            if (resource) {
                this.throwLimit(resource)
            }
            throw error
        }

        this.renderDurationMs += performance.now() - startedAt
        if (this.renderDurationMs > this.limits.maxRenderDurationMs) {
            this.throwLimit('render')
        }

        this.outputBytes += Buffer.byteLength(result, 'utf8')
        if (this.outputBytes > this.limits.maxOutputBytes) {
            this.throwLimit('output')
        }
        return result
    }

    getStats(): LiquidRenderBudgetStats {
        return {
            attempted: this.attempted,
            sourceBytes: this.sourceBytes,
            renderDurationMs: this.renderDurationMs,
            outputBytes: this.outputBytes,
            hardLimit: this.hardLimit,
        }
    }

    getLimits(): LiquidRenderLimits {
        return this.limits
    }

    private throwLimit(resource: LiquidResourceLimit): never {
        this.hardLimit = resource
        throw new LiquidTemplateResourceLimitError(resource)
    }
}
