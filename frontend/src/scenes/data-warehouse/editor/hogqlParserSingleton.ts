import createHogQLParser, { type HogQLParser } from '@posthog/hogql-parser'

let parserPromise: Promise<HogQLParser> | null = null

function getParser(): Promise<HogQLParser> {
    if (!parserPromise) {
        parserPromise = createHogQLParser().catch((error) => {
            // Reset so next call retries initialization
            parserPromise = null
            throw error
        })
    }
    return parserPromise
}

export async function parseSelect(input: string, isInternal?: boolean): Promise<string> {
    const parser = await getParser()
    return parser.parseSelect(input, isInternal)
}

export async function parseExpr(input: string, isInternal?: boolean): Promise<string> {
    const parser = await getParser()
    return parser.parseExpr(input, isInternal)
}

export async function parseOrderExpr(input: string, isInternal?: boolean): Promise<string> {
    const parser = await getParser()
    return parser.parseOrderExpr(input, isInternal)
}

export async function parseProgram(input: string, isInternal?: boolean): Promise<string> {
    const parser = await getParser()
    return parser.parseProgram(input, isInternal)
}

export async function parseFullTemplateString(input: string, isInternal?: boolean): Promise<string> {
    const parser = await getParser()
    return parser.parseFullTemplateString(input, isInternal)
}

export async function parseStringLiteralText(input: string): Promise<string> {
    const parser = await getParser()
    return parser.parseStringLiteralText(input)
}
