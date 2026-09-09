import { readPath } from '../../paths'
import { Scope } from '../../scope'
import { Expr } from './base'

export class PathExpr extends Expr {
    constructor(private readonly segments: string[]) {
        super()
    }
    eval(scope: Scope): unknown {
        return readPath(scope.input, this.segments)
    }
}
