/**
 * React Hooks for HogQL Parser
 *
 * React-specific hooks for working with the HogQL WASM parser
 */

import { useEffect, useState } from 'react'
import type { HogQLParser } from '@posthog/hogql-parser'
import type { Expr, SelectQuery } from './ast'
import { getHogQLParser, parseHogQLSelect, parseHogQLExpr, isParseError, type ParseResult } from './parser'

// ====================================
// useHogQLParser Hook
// ====================================

/**
 * React hook to load and access the HogQL parser singleton
 *
 * @returns Object with parser instance, loading state, and error
 *
 * @example
 * ```typescript
 * function MyComponent() {
 *   const { parser, loading, error } = useHogQLParser()
 *
 *   if (loading) return <div>Loading parser...</div>
 *   if (error) return <div>Error: {error.message}</div>
 *   if (!parser) return null
 *
 *   const result = parser.parseExpr('user_id + 100')
 *   // ...
 * }
 * ```
 */
export function useHogQLParser(): {
    parser: HogQLParser | null
    loading: boolean
    error: Error | null
} {
    const [parser, setParser] = useState<HogQLParser | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<Error | null>(null)

    useEffect(() => {
        getHogQLParser()
            .then((p) => {
                setParser(p)
                setLoading(false)
            })
            .catch((err) => {
                setError(err)
                setLoading(false)
            })
    }, [])

    return { parser, loading, error }
}

// ====================================
// useHogQLExpr Hook
// ====================================

/**
 * React hook to parse a HogQL expression with automatic re-parsing on input change
 *
 * @param input - The HogQL expression to parse
 * @param isInternal - If true, omits position information
 * @returns Object with AST, loading state, and error
 *
 * @example
 * ```typescript
 * function ExpressionEditor({ expression }: { expression: string }) {
 *   const { ast, loading, error } = useHogQLExpr(expression)
 *
 *   if (loading) return <div>Parsing...</div>
 *   if (error) return <div>Error: {error.message}</div>
 *
 *   return <pre>{JSON.stringify(ast, null, 2)}</pre>
 * }
 * ```
 */
export function useHogQLExpr(
    input: string,
    isInternal = false
): {
    ast: ParseResult<Expr> | null
    loading: boolean
    error: Error | null
} {
    const [ast, setAst] = useState<ParseResult<Expr> | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<Error | null>(null)

    useEffect(() => {
        if (!input) {
            setAst(null)
            setLoading(false)
            return
        }

        setLoading(true)
        setError(null)

        parseHogQLExpr(input, isInternal)
            .then((result) => {
                setAst(result)
                setLoading(false)
            })
            .catch((err) => {
                setError(err)
                setLoading(false)
            })
    }, [input, isInternal])

    return { ast, loading, error }
}

// ====================================
// useHogQLSelect Hook
// ====================================

/**
 * React hook to parse a HogQL SELECT statement with automatic re-parsing on query change
 *
 * @param query - The SELECT statement to parse
 * @param isInternal - If true, omits position information
 * @returns Object with AST, loading state, and error
 *
 * @example
 * ```typescript
 * function QueryEditor({ query }: { query: string }) {
 *   const { ast, loading, error } = useHogQLSelect(query)
 *
 *   if (loading) return <div>Parsing...</div>
 *
 *   if (ast && isParseError(ast)) {
 *     return <div>Parse Error: {ast.message}</div>
 *   }
 *
 *   return <pre>{JSON.stringify(ast, null, 2)}</pre>
 * }
 * ```
 */
export function useHogQLSelect(
    query: string,
    isInternal = false
): {
    ast: ParseResult<SelectQuery> | null
    loading: boolean
    error: Error | null
} {
    const [ast, setAst] = useState<ParseResult<SelectQuery> | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<Error | null>(null)

    useEffect(() => {
        if (!query) {
            setAst(null)
            setLoading(false)
            return
        }

        setLoading(true)
        setError(null)

        parseHogQLSelect(query, isInternal)
            .then((result) => {
                setAst(result)
                setLoading(false)
            })
            .catch((err) => {
                setError(err)
                setLoading(false)
            })
    }, [query, isInternal])

    return { ast, loading, error }
}

// ====================================
// useHogQLValidation Hook
// ====================================

/**
 * React hook to validate HogQL syntax with debouncing
 *
 * @param input - The HogQL input to validate
 * @param debounceMs - Debounce delay in milliseconds (default: 300)
 * @returns Object with validation state
 *
 * @example
 * ```typescript
 * function ValidatedInput({ value, onChange }: InputProps) {
 *   const { isValid, error, validating } = useHogQLValidation(value)
 *
 *   return (
 *     <div>
 *       <input value={value} onChange={onChange} />
 *       {validating && <span>Validating...</span>}
 *       {!isValid && error && <span className="error">{error.message}</span>}
 *       {isValid && <span className="success">✓ Valid</span>}
 *     </div>
 *   )
 * }
 * ```
 */
export function useHogQLValidation(
    input: string,
    debounceMs = 300
): {
    isValid: boolean
    error: ParseResult<Expr> | null
    validating: boolean
} {
    const [isValid, setIsValid] = useState(true)
    const [error, setError] = useState<ParseResult<Expr> | null>(null)
    const [validating, setValidating] = useState(false)

    useEffect(() => {
        if (!input) {
            setIsValid(true)
            setError(null)
            setValidating(false)
            return
        }

        setValidating(true)

        const timeoutId = setTimeout(() => {
            parseHogQLExpr(input)
                .then((result) => {
                    if (isParseError(result)) {
                        setIsValid(false)
                        setError(result)
                    } else {
                        setIsValid(true)
                        setError(null)
                    }
                    setValidating(false)
                })
                .catch(() => {
                    setIsValid(false)
                    setValidating(false)
                })
        }, debounceMs)

        return () => clearTimeout(timeoutId)
    }, [input, debounceMs])

    return { isValid, error, validating }
}
