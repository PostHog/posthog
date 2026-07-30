import fs from 'fs'

import { parseJSON } from '~/common/utils/json-parse'
import { CAPTURE_PRODUCED_WARNING_TYPES } from '~/ingestion/common/ingestion-warning-types'
import {
    RUST_GENERATED_JSON_PATH,
    buildCaptureWarningTypesJson,
} from '~/ingestion/common/scripts/generate-ingestion-warning-types'

describe('capture warning types codegen', () => {
    it('committed Rust artifact matches the generator output', () => {
        const committed = fs.readFileSync(RUST_GENERATED_JSON_PATH, 'utf8')
        expect(committed).toEqual(buildCaptureWarningTypesJson())
        // If this fails, INGESTION_WARNING_TYPES changed without regenerating the artifact the
        // Rust build reads. Run `pnpm --filter=@posthog/nodejs gen:ingestion-warning-types`.
    })

    it('artifact lists exactly the capture-produced types in stable sorted order', () => {
        const { types } = parseJSON(fs.readFileSync(RUST_GENERATED_JSON_PATH, 'utf8')) as { types: string[] }
        expect(types).toEqual([...CAPTURE_PRODUCED_WARNING_TYPES].sort())
    })
})
