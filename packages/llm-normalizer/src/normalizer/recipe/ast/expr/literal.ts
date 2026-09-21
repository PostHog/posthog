import { Expr } from './base'

export class LiteralExpr extends Expr {
    constructor(readonly value: unknown) {
        super()
    }
    eval(): unknown {
        return this.value
    }
}
