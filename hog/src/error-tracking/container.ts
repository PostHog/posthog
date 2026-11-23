import { createHash } from 'node:crypto'

// The types of the symbol-data container from the posthog-symbol-data crate (0.5.2).
export enum SymbolDataType {
    SourceAndMap = 2,
    HermesMap = 3,
    ProguardMapping = 4,
    AppleDsym = 5,
    ElfDebugInfo = 6,
}

// SHA-512 over the parts joined with nothing in between, as lowercase hex. Most uploads hash their
// whole container this way.
export function contentHash(...parts: (Uint8Array | string)[]): string {
    const hash = createHash('sha512')
    for (const part of parts) {
        hash.update(part)
    }
    return hash.digest('hex')
}
