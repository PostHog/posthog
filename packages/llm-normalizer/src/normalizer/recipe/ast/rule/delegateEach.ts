import type { CompatMessage } from '../../../../types'
import type { Scope } from '../../scope'
import type { EmitSpec, FollowupSpec } from '../../spec/emitSpec'
import type { Expr } from '../expr'
import type { Pattern } from '../predicate'
import { Rule } from './base'
import { DispatchEngine, NO_MATCH } from './dispatch'

export class DelegateEachRule extends Rule {
    constructor(
        on: Pattern,
        followups: FollowupSpec[],
        private readonly source: Expr,
        private readonly stamp: EmitSpec | null
    ) {
        super(on, followups)
    }
    produce(scope: Scope, engine: DispatchEngine, _allowDrop: boolean, depth: number): CompatMessage[] {
        const arr = this.source.eval(scope)
        if (!Array.isArray(arr)) {
            return []
        }
        const messages: CompatMessage[] = []
        for (const item of arr) {
            const sub = engine.dispatch(item, scope.role, depth + 1)
            if (sub !== NO_MATCH) {
                messages.push(...sub)
            }
        }
        if (!this.stamp) {
            return messages
        }
        return messages.map((msg) => engine.coercer.stamp(msg, this.stamp!, scope))
    }
}
