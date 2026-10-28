import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { defineCommand } from '@/core/command'
import { HogError } from '@/core/errors'
import type { Output } from '@/core/output'
import { deriveBaseName, extractSymbolSet, type ExtractReport } from '@/error-tracking/symbols'

const KIND_LABELS: Record<ExtractReport['kind'], string> = {
    sourcemap: 'JavaScript',
    hermes: 'Hermes',
    proguard: 'ProGuard',
    elf: 'ELF',
    dsym: 'dSYM',
}

export function renderExtracted(out: Output, result: ExtractReport): void {
    for (const file of result.files) {
        out.line(file)
    }
    out.line(out.style(`Extracted the ${KIND_LABELS[result.kind]} symbol set to ${result.output}.`, 'dim'))
}

export default defineCommand({
    description: 'Unpack a symbol set file, such as one PostHog stored',
    args: {
        file: { description: 'The symbol set file' },
    },
    options: {
        outputDir: { type: 'string', placeholder: 'folder', description: 'Where to write the files (default .)' },
    },
    examples: ['hog error-tracking extract symbol-set.bin --output-dir symbols'],

    async run({ args, options, ctx }) {
        let data: Uint8Array
        try {
            data = readFileSync(resolve(ctx.runtime.cwd(), args.file))
        } catch (error) {
            throw new HogError('file_unreadable', `hog couldn't read ${args.file}: ${(error as Error).message}`)
        }
        const name =
            args.file
                .split('/')
                .filter((part) => part !== '' && part !== '.')
                .pop() ?? 'symbol_set'
        return extractSymbolSet(data, deriveBaseName(name), options.outputDir ?? '.', ctx.runtime.cwd())
    },

    human({ result, out }) {
        renderExtracted(out, result)
    },
})
