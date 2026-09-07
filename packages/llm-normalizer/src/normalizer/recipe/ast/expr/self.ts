import { Scope } from '../../scope'
import { Expr } from './base'

export class SelfExpr extends Expr {
    eval(scope: Scope): unknown {
        return scope.input
    }
}
