// TC39 JSON.parse source text access. Bun supports it, and TypeScript's lib doesn't declare it yet.
interface RawJSON {
    readonly rawJSON: string
}

interface JSONReviverContext {
    readonly source?: string
}

interface JSON {
    parse(
        text: string,
        reviver: (this: unknown, key: string, value: unknown, context: JSONReviverContext) => unknown
    ): unknown
    rawJSON(text: string): RawJSON
    isRawJSON(value: unknown): value is RawJSON
}
