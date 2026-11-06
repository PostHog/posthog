import { Scope } from '../../scope'
import { Expr } from './base'

export class CoalesceExpr extends Expr {
    constructor(private readonly from: Expr) {
        super()
    }
    eval(scope: Scope): unknown {
        const list = this.from.eval(scope)
        if (!Array.isArray(list)) {
            return undefined
        }
        return list.find((v) => v !== undefined && v !== null)
    }
}
