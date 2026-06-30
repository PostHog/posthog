import { Scope } from '../../scope'
import { Pattern } from '../predicate'
import { Expr } from './base'

export abstract class FilterExpr extends Expr {
    protected constructor(
        protected readonly from: Expr,
        protected readonly where: Pattern | null,
        protected readonly ifEmpty: Expr | null
    ) {
        super()
    }

    protected onNotArray(scope: Scope): unknown {
        const fb = this.ifEmpty ? this.ifEmpty.eval(scope) : undefined
        return fb ?? []
    }

    protected withIfEmpty(result: unknown[], scope: Scope): unknown {
        if (result.length !== 0 || this.ifEmpty === null) {
            return result
        }
        const fallback = this.ifEmpty.eval(scope)
        // `if_empty: ~` (null) becomes undefined so the emit slot drops the field entirely.
        return fallback === null ? undefined : fallback
    }
}
