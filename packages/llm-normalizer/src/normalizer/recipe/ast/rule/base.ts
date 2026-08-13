import type { CompatMessage } from '../../../../types'
import type { Scope } from '../../scope'
import type { FollowupSpec } from '../../spec/emitSpec'
import type { Pattern } from '../predicate'
import type { DispatchEngine } from './dispatch'

export abstract class Rule {
    constructor(
        readonly on: Pattern,
        private readonly followups: FollowupSpec[]
    ) {}

    abstract produce(scope: Scope, engine: DispatchEngine, allowDrop: boolean, depth: number): CompatMessage[]

    buildFollowups(scope: Scope, engine: DispatchEngine): CompatMessage[] {
        const messages: CompatMessage[] = []
        for (const followup of this.followups) {
            if (followup.kind === 'static') {
                const msg = engine.coercer.buildMessage(followup.emit, scope, /* allowDrop */ true)
                if (msg) {
                    messages.push(msg)
                }
                continue
            }
            const arr = followup.from.eval(scope)
            if (!Array.isArray(arr)) {
                continue
            }
            for (const item of arr) {
                const msg = engine.coercer.buildMessage(followup.each, scope.withInput(item))
                if (msg) {
                    messages.push(msg)
                }
            }
        }
        return messages
    }
}
