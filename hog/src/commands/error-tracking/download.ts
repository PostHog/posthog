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
    writes: true,
    args: {
        symbolSet: { description: 'The symbol set ID, or its ref, such as static/chunks/app.js.map' },
    },
    options: {
        outputDir: { type: 'string', placeholder: 'folder', description: 'Where to write the files (default .)' },
        ref: {
            type: 'boolean',
            description: 'Look the argument up as a ref, for refs that look like IDs, such as chunk IDs and debug IDs',
        },
        dryRun: { type: 'boolean', description: 'Download the symbol set and list its files without writing them' },
    },
    scopes: ['error_tracking:read'],
    notes: 'A sourcemap becomes a .js and a .js.map file, a Hermes map a .hbc.map file, a ProGuard mapping a .txt file, and a dSYM or ELF symbol set a folder.',
    examples: [
        'hog error-tracking download static/chunks/app.js.map',
        'hog et download 0192f0a0-0000-7000-8000-000000000001 --output-dir symbols',
        'hog et download 3f161e6c-fc03-5fe2-a9e9-08e5ae65fd15 --ref',
    ],

    async run({ args, options, ctx }) {
        const client = new SymbolSetClient(ctx.runtime, await ctx.credentials())
        const byId = !options.ref && isSymbolSetId(args.symbolSet)
        const id = byId ? args.symbolSet : await resolveRef(client, args.symbolSet)
        const data = await downloadSymbolSet(client, id, ctx.runtime.fetch)
        const dryRun = options.dryRun === true
        return {
            id,
            dryRun,
            ...extractSymbolSet(
                data,
                byId ? id : deriveBaseName(args.symbolSet),
                options.outputDir ?? '.',
                ctx.runtime.cwd(),
                dryRun
            ),
        }
    },

    human({ result, out }) {
        renderExtracted(out, result)
    },
})
