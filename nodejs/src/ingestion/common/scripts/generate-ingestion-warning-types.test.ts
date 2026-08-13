import fs from 'fs'

import { parseJSON } from '~/common/utils/json-parse'
import { CAPTURE_PRODUCED_WARNING_TYPES, INGESTION_WARNING_TYPES } from '~/ingestion/common/ingestion-warning-types'
import {
    RUST_GENERATED_JSON_PATH,
    buildWarningTypesJson,
} from '~/ingestion/common/scripts/generate-ingestion-warning-types'

describe('warning types codegen', () => {
    it('committed Rust artifact matches the generator output', () => {
        const committed = fs.readFileSync(RUST_GENERATED_JSON_PATH, 'utf8')
        expect(committed).toEqual(buildWarningTypesJson())
        // If this fails, INGESTION_WARNING_TYPES changed without regenerating the artifact the
        // Rust build reads. Run `pnpm --filter=@posthog/nodejs gen:ingestion-warning-types`.
    })

    it('artifact lists every registry type with its classification in stable sorted order', () => {
        const { types } = parseJSON(fs.readFileSync(RUST_GENERATED_JSON_PATH, 'utf8')) as {
            types: { type: string; category: string; severity: string; captureProduced: boolean }[]
        }
        expect(types.map((t) => t.type)).toEqual(Object.keys(INGESTION_WARNING_TYPES).sort())
        for (const entry of types) {
            expect(entry.category).toEqual(
                INGESTION_WARNING_TYPES[entry.type as keyof typeof INGESTION_WARNING_TYPES].category
            )
            expect(entry.severity).toEqual(
                INGESTION_WARNING_TYPES[entry.type as keyof typeof INGESTION_WARNING_TYPES].severity
            )
            expect(entry.captureProduced).toEqual(
                CAPTURE_PRODUCED_WARNING_TYPES.has(entry.type as keyof typeof INGESTION_WARNING_TYPES)
            )
        }
    })
})
