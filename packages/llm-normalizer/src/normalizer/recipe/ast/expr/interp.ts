import { Scope } from '../../scope'
import { Expr } from './base'

export class InterpExpr extends Expr {
    constructor(private readonly parts: (string | Expr)[]) {
        super()
    }
    eval(scope: Scope): unknown {
        return this.parts.map((part) => (typeof part === 'string' ? part : String(part.eval(scope) ?? ''))).join('')
    }
}
