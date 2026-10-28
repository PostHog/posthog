import { describe, expect, test } from 'bun:test'

import { contentHash, SymbolDataType, writeSymbolData } from '@/error-tracking/container'

import golden from './golden/containers.json'
import { generateInput } from './inputs'

const TYPES = {
    proguard: SymbolDataType.ProguardMapping,
    hermes: SymbolDataType.HermesMap,
    dsym: SymbolDataType.AppleDsym,
    elf: SymbolDataType.ElfDebugInfo,
} as const

// Each golden comes from posthog-cli's own container code (cli/examples/hog_parity_oracle.rs). A
// mismatch here means hog would upload different bytes than posthog-cli, and PostHog would reject
// a re-upload of the same file with `content_hash_mismatch`.
describe('symbol set containers match posthog-cli byte for byte', () => {
    test.each(
        golden.map(
            (testCase) =>
                [`${testCase.type} ${testCase.input.generator} ${testCase.input.size} bytes`, testCase] as const
        )
    )('%s', (_name, testCase) => {
        const container = writeSymbolData(
            TYPES[testCase.type as keyof typeof TYPES],
            generateInput(testCase.input as never)
        )
        expect(contentHash(container)).toBe(testCase.hash)
    })
})
