import { Scope } from '../../scope'
import { Pattern } from '../predicate'
import { Expr } from './base'
import { FilterExpr } from './filter'

export class SelectExpr extends FilterExpr {
    constructor(
        from: Expr,
        where: Pattern | null,
        private readonly pluck: Expr | null,
        ifEmpty: Expr | null
    ) {
        super(from, where, ifEmpty)
    }
    eval(scope: Scope): unknown {
        const arr = this.from.eval(scope)
        if (!Array.isArray(arr)) {
            return this.onNotArray(scope)
        }
        const filtered = this.where ? arr.filter((item) => this.where!.matches(item)) : arr
        let result: unknown[] = filtered
        if (this.pluck) {
            result = filtered.map((item) => this.pluck!.eval(scope.withInput(item))).filter((v) => v != null)
        }
        return this.withIfEmpty(result, scope)
    }
}
