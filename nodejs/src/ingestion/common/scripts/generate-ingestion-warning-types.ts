import fs from 'fs'
import path from 'path'

import { CAPTURE_PRODUCED_WARNING_TYPES } from '~/ingestion/common/ingestion-warning-types'

/**
 * Codegen for the cross-language ingestion-warning contract.
 *
 * `INGESTION_WARNING_TYPES` (nodejs/src/ingestion/common/ingestion-warning-types.ts) is the single
 * source of truth. Entries flagged `captureProduced: true` are the types Rust capture may emit; this
 * script mirrors that set into a JSON artifact committed inside the Rust crate, from which
 * `rust/common/ingestion_warnings/build.rs` generates the `WarningType` enum. Committing the artifact
 * (rather than reading the .ts from Rust) keeps the isolated Rust Docker/CI build context self-contained.
 *
 * Run: `pnpm --filter=@posthog/nodejs gen:ingestion-warning-types`
 * The no-drift Jest test (`generate-ingestion-warning-types.test.ts`) fails CI if the committed
 * artifact and this output diverge.
 */

const REPO_ROOT = path.resolve(__dirname, '../../../../..')

/** Absolute path of the committed artifact consumed by the Rust build. */
export const RUST_GENERATED_JSON_PATH = path.join(
    REPO_ROOT,
    'rust/common/ingestion_warnings/capture_warning_types.generated.json'
)

/**
 * Canonical artifact contents: a stable, sorted set of the capture-produced warning type strings.
 * Only the type strings cross the boundary — category/severity are resolved Node-side at
 * serialization time, and the Rust pipeline step is a constant, so neither belongs here.
 */
export function buildCaptureWarningTypesJson(): string {
    const types = [...CAPTURE_PRODUCED_WARNING_TYPES].sort()
    const artifact = {
        _comment:
            'GENERATED from INGESTION_WARNING_TYPES (captureProduced) in ' +
            'nodejs/src/ingestion/common/ingestion-warning-types.ts via ' +
            '`pnpm --filter=@posthog/nodejs gen:ingestion-warning-types`. Do not edit by hand; ' +
            'rust/common/ingestion_warnings/build.rs codegens the WarningType enum from this file.',
        types,
    }
    // 2-space indent + trailing newline matches Prettier's JSON default, so the artifact stays
    // byte-stable across formatters and the no-drift test can compare exact contents.
    return JSON.stringify(artifact, null, 2) + '\n'
}

function main(): void {
    const contents = buildCaptureWarningTypesJson()
    fs.writeFileSync(RUST_GENERATED_JSON_PATH, contents)
    console.log(
        `Wrote ${[...CAPTURE_PRODUCED_WARNING_TYPES].length} capture warning types to ${RUST_GENERATED_JSON_PATH}`
    )
}

if (require.main === module) {
    main()
}
