import { readFileSync } from 'node:fs'
import { basename, resolve } from 'node:path'

import { defineCommand } from '@/core/command'
import { HogError } from '@/core/errors'
import { escapeControls, type Output } from '@/core/output'
import { deriveBaseName, extractSymbolSet, type ExtractReport } from '@/error-tracking/symbols'

const KIND_LABELS: Record<ExtractReport['kind'], string> = {
    sourcemap: 'JavaScript',
    hermes: 'Hermes',
    proguard: 'ProGuard',
    elf: 'ELF',
    dsym: 'dSYM',
}

export function renderExtracted(out: Output, result: ExtractReport & { dryRun: boolean }): void {
    for (const file of result.files) {
        out.line(escapeControls(file))
    }
    const verb = result.dryRun ? 'Dry run: would extract' : 'Extracted'
    out.line(
        out.style(`${verb} the ${KIND_LABELS[result.kind]} symbol set to ${escapeControls(result.output)}.`, 'dim')
    )
}

export default defineCommand({
    description: 'Unpack a symbol set file, such as one PostHog stored',
    writes: true,
    args: {
        file: { description: 'The symbol set file' },
    },
    options: {
        outputDir: { type: 'string', placeholder: 'folder', description: 'Where to write the files (default .)' },
        dryRun: { type: 'boolean', description: 'List the files without writing them' },
    },
    examples: ['hog error-tracking extract symbol-set.bin --output-dir symbols'],

    async run({ args, options, ctx }) {
        let data: Uint8Array
        try {
            data = readFileSync(resolve(ctx.runtime.cwd(), args.file))
        } catch (error) {
            throw new HogError('file_unreadable', `hog couldn't read ${args.file}: ${(error as Error).message}`)
        }
        const dryRun = options.dryRun === true
        return {
            dryRun,
            ...extractSymbolSet(
                data,
                deriveBaseName(basename(args.file) || 'symbol_set'),
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
