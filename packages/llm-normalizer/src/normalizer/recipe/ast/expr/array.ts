import { Scope } from '../../scope'
import { Expr } from './base'

export class ArrayExpr extends Expr {
    constructor(private readonly items: Expr[]) {
        super()
    }
    eval(scope: Scope): unknown {
        return this.items.map((item) => item.eval(scope))
    }
}
