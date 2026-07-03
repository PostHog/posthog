// `decodeURIComponent` throws `URIError: URI malformed` on a stray or truncated
// percent escape (`%`, `%a`, `%zz`). The connection-string parsers run on every
// keystroke against half-typed input, so a raw decode crashes the form's paste-to-
// auto-fill path. Fall back to the raw value when the input can't be decoded — a
// partially-typed field is better than an uncaught exception.
export function safeDecodeURIComponent(value: string): string {
    try {
        return decodeURIComponent(value)
    } catch {
        return value
    }
}
