/**
 * HogQL Parser - WebAssembly Singleton
 *
 * Provides a singleton instance of the HogQL WASM parser with async initialization.
 * The parser is loaded once and reused across the application.
 */
import createHogQLParser from '@posthog/hogql-parser'
import type { HogQLParser } from '@posthog/hogql-parser'

import type {
    AST,
    ArithmeticOperation,
    Call,
    CompareOperation,
    Constant,
    Expr,
    Field,
    OrderExpr,
    Program,
    SelectQuery,
} from './ast'

// ====================================
// Type Definitions
// ====================================

/**
 * Parse error with proper typing from ast.ts
 */
export interface ParseError extends AST {
    error: true
    type: 'SyntaxError' | 'ParsingError' | 'NotImplementedError'
    message: string
}

/**
 * Parse result can be either a specific AST node type
 */
export type ParseResult<T extends AST = AST> = T

// ====================================
// Singleton Parser Instance
// ====================================

let parserInstance: HogQLParser | null = null
let parserPromise: Promise<HogQLParser> | null = null

/**
 * Get the singleton HogQL parser instance.
 * The parser is loaded asynchronously on first call and cached for subsequent calls.
 *
 * @returns Promise that resolves to the HogQL parser instance
 *
 * @example
 * ```typescript
 * const parser = await getHogQLParser()
 * const ast = parser.parseExpr('user_id + 100')
 * ```
 */
export async function getHogQLParser(): Promise<HogQLParser> {
    // Return cached instance if available
    if (parserInstance) {
        return parserInstance
    }

    // Return existing promise if loading
    if (parserPromise) {
        return parserPromise
    }

    // Create new parser instance
    parserPromise = createHogQLParser().then((parser) => {
        parserInstance = parser
        return parser
    })

    return parserPromise
}

/**
 * Reset the parser singleton (useful for testing)
 */
export function resetHogQLParser(): void {
    parserInstance = null
    parserPromise = null
}

// ====================================
// Convenience Functions
// ====================================

/**
 * Parse a HogQL expression and return the AST
 *
 * @param input - The HogQL expression to parse
 * @param isInternal - If true, omits position information from AST
 * @returns Parsed Expr AST or error object
 *
 * @example
 * ```typescript
 * const ast = await parseHogQLExpr('user_id + 100')
 * if ('error' in ast) {
 *   console.error('Parse error:', ast.message)
 * } else {
 *   console.log('Expression:', ast)
 * }
 * ```
 */
export async function parseHogQLExpr(input: string, isInternal = false): Promise<ParseResult<Expr>> {
    const parser = await getHogQLParser()
    const result = parser.parseExpr(input, isInternal)
    return JSON.parse(result) as ParseResult<Expr>
}

/**
 * Parse a complete SELECT statement and return the AST
 *
 * @param input - The SELECT statement to parse
 * @param isInternal - If true, omits position information from AST
 * @returns Parsed SelectQuery AST or error object
 *
 * @example
 * ```typescript
 * const ast = await parseHogQLSelect('SELECT * FROM events WHERE timestamp > now()')
 * if ('error' in ast) {
 *   console.error('Parse error:', ast.message)
 * } else {
 *   console.log('Query:', ast)
 * }
 * ```
 */
export async function parseHogQLSelect(input: string, isInternal = false): Promise<ParseResult<SelectQuery>> {
    const parser = await getHogQLParser()
    const result = parser.parseSelect(input, isInternal)
    return JSON.parse(result) as ParseResult<SelectQuery>
}

/**
 * Parse an ORDER BY expression
 *
 * @param input - The ORDER BY expression to parse
 * @param isInternal - If true, omits position information from AST
 * @returns Parsed OrderExpr AST or error object
 *
 * @example
 * ```typescript
 * const ast = await parseHogQLOrderExpr('timestamp DESC, user_id ASC')
 * ```
 */
export async function parseHogQLOrderExpr(input: string, isInternal = false): Promise<ParseResult<OrderExpr>> {
    const parser = await getHogQLParser()
    const result = parser.parseOrderExpr(input, isInternal)
    return JSON.parse(result) as ParseResult<OrderExpr>
}

/**
 * Parse a Hog program
 *
 * @param input - The Hog program to parse
 * @param isInternal - If true, omits position information from AST
 * @returns Parsed Program AST or error object
 *
 * @example
 * ```typescript
 * const ast = await parseHogQLProgram('let x := 42; return x;')
 * ```
 */
export async function parseHogQLProgram(input: string, isInternal = false): Promise<ParseResult<Program>> {
    const parser = await getHogQLParser()
    const result = parser.parseProgram(input, isInternal)
    return JSON.parse(result) as ParseResult<Program>
}

/**
 * Parse a Hog template string (f'...' syntax)
 *
 * @param input - The template string to parse
 * @param isInternal - If true, omits position information from AST
 * @returns Parsed Expr AST or error object
 *
 * @example
 * ```typescript
 * const ast = await parseHogQLTemplateString("f'Hello {name}'")
 * ```
 */
export async function parseHogQLTemplateString(input: string, isInternal = false): Promise<ParseResult<Expr>> {
    const parser = await getHogQLParser()
    const result = parser.parseFullTemplateString(input, isInternal)
    return JSON.parse(result) as ParseResult<Expr>
}

/**
 * Unquote a string literal
 *
 * @param input - The quoted string literal
 * @returns The unquoted string content
 *
 * @example
 * ```typescript
 * const text = await parseHogQLStringLiteral("'hello world'")
 * // Returns: "hello world"
 * ```
 */
export async function parseHogQLStringLiteral(input: string): Promise<string> {
    const parser = await getHogQLParser()
    return parser.parseStringLiteralText(input)
}

// ====================================
// Type Guards
// ====================================

/**
 * Check if a parse result is an error
 */
export function isParseError<T extends AST>(result: ParseResult<T>): result is ParseError {
    return 'error' in result && result.error === true
}

/**
 * Check if a parse result is a valid AST node
 */
export function isASTNode<T extends AST>(result: ParseResult<T>): result is T {
    return !('error' in result)
}

// ====================================
// Validation Helpers
// ====================================

/**
 * Validate a HogQL expression without throwing
 *
 * @param input - The HogQL expression to validate
 * @returns Object with isValid flag and optional error
 *
 * @example
 * ```typescript
 * const { isValid, error } = await validateHogQLExpr('user_id + ')
 * if (!isValid) {
 *   console.error('Invalid expression:', error?.message)
 * }
 * ```
 */
export async function validateHogQLExpr(input: string): Promise<{ isValid: boolean; error?: ParseError; ast?: Expr }> {
    try {
        const result = await parseHogQLExpr(input)
        if (isParseError(result)) {
            return { isValid: false, error: result }
        }
        return { isValid: true, ast: result }
    } catch (err) {
        return {
            isValid: false,
            error: {
                error: true,
                type: 'ParsingError',
                message: err instanceof Error ? err.message : 'Unknown error',
                start: { line: 0, column: 0, offset: 0 },
                end: { line: 0, column: 0, offset: 0 },
            },
        }
    }
}

/**
 * Validate a HogQL SELECT statement without throwing
 *
 * @param input - The SELECT statement to validate
 * @returns Object with isValid flag and optional error
 */
export async function validateHogQLSelect(
    input: string
): Promise<{ isValid: boolean; error?: ParseError; ast?: SelectQuery }> {
    try {
        const result = await parseHogQLSelect(input)
        if (isParseError(result)) {
            return { isValid: false, error: result }
        }
        return { isValid: true, ast: result }
    } catch (err) {
        return {
            isValid: false,
            error: {
                error: true,
                type: 'ParsingError',
                message: err instanceof Error ? err.message : 'Unknown error',
                start: { line: 0, column: 0, offset: 0 },
                end: { line: 0, column: 0, offset: 0 },
            },
        }
    }
}

// ====================================
// Export Types
// ====================================

export type { HogQLParser }
export type { SelectQuery, Expr, Program, OrderExpr, Field, Constant, Call, ArithmeticOperation, CompareOperation, AST }
