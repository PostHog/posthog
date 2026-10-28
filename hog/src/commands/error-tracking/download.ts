import { defineCommand } from '@/core/command'
import {
    downloadSymbolSet,
    deriveBaseName,
    extractSymbolSet,
    isSymbolSetId,
    resolveRef,
} from '@/error-tracking/symbols'
import { SymbolSetClient } from '@/error-tracking/upload'

import { renderExtracted } from './extract'

export default defineCommand({
    description: 'Download a symbol set from PostHog and unpack it',
    args: {
        symbolSet: { description: 'The symbol set ID, or its ref, such as static/chunks/app.js.map' },
    },
    options: {
        outputDir: { type: 'string', placeholder: 'folder', description: 'Where to write the files (default .)' },
    },
    scopes: ['error_tracking:read'],
    notes: 'A sourcemap becomes a .js and a .js.map file, a Hermes map a .hbc.map file, a ProGuard mapping a .txt file, and a dSYM or ELF symbol set a folder.',
    examples: [
        'hog error-tracking download static/chunks/app.js.map',
        'hog et download 0192f0a0-0000-7000-8000-000000000001 --output-dir symbols',
    ],

    async run({ args, options, ctx }) {
        const client = new SymbolSetClient(ctx.runtime, await ctx.credentials())
        const byId = isSymbolSetId(args.symbolSet)
        const id = byId ? args.symbolSet : await resolveRef(client, args.symbolSet)
        const data = await downloadSymbolSet(client, id, ctx.runtime.fetch)
        return {
            id,
            ...extractSymbolSet(
                data,
                byId ? id : deriveBaseName(args.symbolSet),
                options.outputDir ?? '.',
                ctx.runtime.cwd()
            ),
        }
    },

    human({ result, out }) {
        renderExtracted(out, result)
    },
})
