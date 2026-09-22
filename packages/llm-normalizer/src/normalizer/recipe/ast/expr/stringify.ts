import { Scope } from '../../scope'
import { Expr } from './base'

// Renders a value as content text. String/array/null/undefined pass through
// (the content slot handles those); everything else is JSON-encoded, falling
// back to String() when JSON.stringify throws (e.g. circular refs).
export class StringifyExpr extends Expr {
    constructor(private readonly input: Expr) {
        super()
    }
    eval(scope: Scope): unknown {
        const value = this.input.eval(scope)
        if (typeof value === 'string' || value === null || value === undefined || Array.isArray(value)) {
            return value
        }
        try {
            return JSON.stringify(value)
        } catch {
            return String(value)
        }
    }
}
