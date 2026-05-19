/**
 * HogQL Parser WebAssembly Module
 *
 * High-performance HogQL parser compiled to WebAssembly.
 * All parse functions return JSON strings that should be parsed with JSON.parse().
 */

/**
 * AST Position information
 */
export interface Position {
    line: number
    column: number
    offset: number
}

/**
 * Base AST node with position information
 */
export interface ASTNode {
    node: string
    start: Position
    end: Position
    [key: string]: any
}

/**
 * Parse error object
 */
export interface ParseError {
    error: true
    type: 'SyntaxError' | 'ParsingError' | 'NotImplementedError'
    message: string
    start: Position
    end: Position
}

/**
 * Parse result - either an AST node or an error
 */
export type ParseResult = ASTNode | ParseError

/**
 * HogQL Parser instance
 */
export interface HogQLParser {
    /**
     * Parse a HogQL expression
     *
     * @param input - The HogQL expression string to parse
     * @param isInternal - If true, omits position information from the AST (default: false)
     * @returns JSON string representing the AST or error
     *
     * @example
     * ```typescript
     * const result = parser.parseExpr('user_id + 100');
     * const ast = JSON.parse(result);
     * ```
     */
    parseExpr(input: string, isInternal?: boolean): string

    /**
     * Parse a complete SELECT statement
     *
     * @param input - The SELECT statement string to parse
     * @param isInternal - If true, omits position information from the AST (default: false)
     * @returns JSON string representing the AST or error
     *
     * @example
     * ```typescript
     * const result = parser.parseSelect('SELECT * FROM events WHERE timestamp > now()');
     * const ast = JSON.parse(result);
     * ```
     */
    parseSelect(input: string, isInternal?: boolean): string

    /**
     * Parse an ORDER BY expression
     *
     * @param input - The ORDER BY expression string to parse
     * @param isInternal - If true, omits position information from the AST (default: false)
     * @returns JSON string representing the AST or error
     *
     * @example
     * ```typescript
     * const result = parser.parseOrderExpr('timestamp DESC, user_id ASC');
     * const ast = JSON.parse(result);
     * ```
     */
    parseOrderExpr(input: string, isInternal?: boolean): string

    /**
     * Parse a complete Hog program
     *
     * @param input - The Hog program string to parse
     * @param isInternal - If true, omits position information from the AST (default: false)
     * @returns JSON string representing the AST or error
     *
     * @example
     * ```typescript
     * const result = parser.parseProgram('let x := 42; return x;');
     * const ast = JSON.parse(result);
     * ```
     */
    parseProgram(input: string, isInternal?: boolean): string

    /**
     * Parse a Hog template string (f'...' syntax)
     *
     * @param input - The template string to parse
     * @param isInternal - If true, omits position information from the AST (default: false)
     * @returns JSON string representing the AST or error
     *
     * @example
     * ```typescript
     * const result = parser.parseFullTemplateString("f'Hello {name}'");
     * const ast = JSON.parse(result);
     * ```
     */
    parseFullTemplateString(input: string, isInternal?: boolean): string

    /**
     * Unquote a string literal
     *
     * @param input - The quoted string literal
     * @returns The unquoted string content
     *
     * @example
     * ```typescript
     * const text = parser.parseStringLiteralText("'hello world'");
     * // Returns: "hello world"
     * ```
     */
    parseStringLiteralText(input: string): string

    /**
     * Pretty-print a SELECT statement (or selectSetStmt — including
     * UNION/INTERSECT/EXCEPT). Best-effort formatter intended for one-shot
     * reformatting (e.g. on paste), not as-you-type. Comments are not
     * preserved in this version.
     *
     * Returns a JSON string with one of two shapes:
     *   - `{"ok": true, "output": "<formatted SQL>"}` on success
     *   - `{"ok": false, "error": "<message>"}` if the input is not a
     *     well-formed select statement, or if the formatter hit an internal
     *     error. Callers should leave the user's text unchanged when
     *     `ok` is false.
     *
     * @param input - The SQL text to format
     * @returns JSON string describing the outcome
     *
     * @example
     * ```typescript
     * const raw = parser.formatSelect('select a,b from events where x=1');
     * const result: FormatResult = JSON.parse(raw);
     * if (result.ok) {
     *   console.log(result.output);
     * }
     * ```
     */
    formatSelect(input: string): string
}

/**
 * Result of `parser.formatSelect()` after JSON.parse.
 */
export type FormatResult = { ok: true; output: string } | { ok: false; error: string }

/**
 * Factory function to create a HogQL Parser instance
 *
 * @returns Promise that resolves to a HogQLParser instance
 *
 * @example
 * ```typescript
 * import createHogQLParser from '@posthog/hogql-parser';
 *
 * const parser = await createHogQLParser();
 * const result = parser.parseExpr('1 + 2');
 * const ast: ParseResult = JSON.parse(result);
 *
 * if ('error' in ast) {
 *   console.error('Parse error:', ast.message);
 * } else {
 *   console.log('Parsed successfully:', ast);
 * }
 * ```
 */
export default function createHogQLParser(): Promise<HogQLParser>
