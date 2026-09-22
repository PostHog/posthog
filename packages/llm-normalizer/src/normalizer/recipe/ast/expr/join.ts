import { readField } from '../../paths'
import { Scope } from '../../scope'
import { Expr } from './base'

export class JoinExpr extends Expr {
    constructor(
        private readonly from: Expr,
        private readonly sep: Expr | null,
        private readonly field: Expr | null
    ) {
        super()
    }
    eval(scope: Scope): unknown {
        const arr = this.from.eval(scope)
        if (!Array.isArray(arr)) {
            return ''
        }
        const sep = this.sep ? this.sep.eval(scope) : undefined
        const field = this.field ? this.field.eval(scope) : undefined
        const sepStr = typeof sep === 'string' ? sep : '\n'
        if (typeof field === 'string') {
            return arr.map((item) => readField(item, field) ?? '').join(sepStr)
        }
        return arr.map((item) => String(item ?? '')).join(sepStr)
    }
}
