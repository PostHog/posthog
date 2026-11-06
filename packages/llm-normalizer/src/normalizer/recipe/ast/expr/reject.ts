import { Scope } from '../../scope'
import { Pattern } from '../predicate'
import { Expr } from './base'
import { FilterExpr } from './filter'

export class RejectExpr extends FilterExpr {
    constructor(from: Expr, where: Pattern | null, ifEmpty: Expr | null) {
        super(from, where, ifEmpty)
    }
    eval(scope: Scope): unknown {
        const arr = this.from.eval(scope)
        if (!Array.isArray(arr)) {
            return this.onNotArray(scope)
        }
        const result = this.where ? arr.filter((item) => !this.where!.matches(item)) : arr
        return this.withIfEmpty(result, scope)
    }
}
