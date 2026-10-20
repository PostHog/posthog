type RustAnonymizer = typeof import('@posthog/replay-anonymizer')

let rustAnonymizer: RustAnonymizer | undefined

// Lazily loaded so deployments that never run the mirror don't pay the native-module load (and so a
// missing addon only breaks the native path, not every import of this module).
export function getRustAnonymizer(): RustAnonymizer {
    if (!rustAnonymizer) {
        rustAnonymizer = require('@posthog/replay-anonymizer') as RustAnonymizer
    }
    return rustAnonymizer
}
