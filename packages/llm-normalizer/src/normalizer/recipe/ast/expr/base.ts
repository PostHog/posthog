import { Scope } from '../../scope'

export abstract class Expr {
    abstract eval(scope: Scope): unknown
}
