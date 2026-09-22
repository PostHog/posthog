import { Scope } from '../../scope'
import { Expr } from './base'

export class ObjectExpr extends Expr {
    constructor(private readonly fields: Record<string, Expr>) {
        super()
    }
    eval(scope: Scope): unknown {
        const out: Record<string, unknown> = {}
        for (const [k, v] of Object.entries(this.fields)) {
            out[k] = v.eval(scope)
        }
        return out
    }
}
