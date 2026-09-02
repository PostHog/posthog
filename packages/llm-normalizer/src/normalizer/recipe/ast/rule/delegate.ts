import type { CompatMessage } from '../../../../types'
import type { Scope } from '../../scope'
import type { FollowupSpec } from '../../spec/emitSpec'
import type { Expr } from '../expr'
import type { Pattern } from '../predicate'
import { Rule } from './base'
import { DispatchEngine, NO_MATCH } from './dispatch'

export class DelegateRule extends Rule {
    constructor(
        on: Pattern,
        followups: FollowupSpec[],
        private readonly source: Expr
    ) {
        super(on, followups)
    }
    produce(scope: Scope, engine: DispatchEngine, _allowDrop: boolean, depth: number): CompatMessage[] {
        const next = this.source.eval(scope)
        const sub = engine.dispatch(next, scope.role, depth + 1)
        return sub === NO_MATCH ? [] : sub
    }
}
