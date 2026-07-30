import fs from 'fs'
import path from 'path'

import { CAPTURE_PRODUCED_WARNING_TYPES, INGESTION_WARNING_TYPES } from '~/ingestion/common/ingestion-warning-types'

/**
 * Codegen for the cross-language ingestion-warning contract.
 *
 * `INGESTION_WARNING_TYPES` (nodejs/src/ingestion/common/ingestion-warning-types.ts) is the single
 * source of truth. This script mirrors the whole registry — every type with its category and
 * severity — into a JSON artifact committed inside the Rust crate, from which
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
    'rust/common/ingestion_warnings/warning_types.generated.json'
)

/**
 * Canonical artifact contents: every registry type with its classification, in stable sorted order.
 * Which producer emits which type is not registry data — Rust callers reference the variants they
 * emit, and the message `source` field records who said it. The one exception is `captureProduced`:
 * it is the consumer-side trust allowlist for the capture envelope, and it is exported so the Rust
 * side can assert its `from_tag` emit allowlist stays exactly equal to it — skew in either
 * direction silently drops warnings (never emitted, or emitted and rejected at the consumer).
 */
export function buildWarningTypesJson(): string {
    const types = (Object.keys(INGESTION_WARNING_TYPES) as (keyof typeof INGESTION_WARNING_TYPES)[])
        .sort()
        .map((type) => ({
            type,
            category: INGESTION_WARNING_TYPES[type].category,
            severity: INGESTION_WARNING_TYPES[type].severity,
            captureProduced: CAPTURE_PRODUCED_WARNING_TYPES.has(type),
        }))
    const artifact = {
        _comment:
            'GENERATED from INGESTION_WARNING_TYPES in ' +
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
    fs.writeFileSync(RUST_GENERATED_JSON_PATH, buildWarningTypesJson())
    console.info(`Wrote ${Object.keys(INGESTION_WARNING_TYPES).length} warning types to ${RUST_GENERATED_JSON_PATH}`)
}

if (require.main === module) {
    main()
}
