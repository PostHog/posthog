import type { CompatMessage } from '../../../../types'
import type { Scope } from '../../scope'
import type { EmitSpec, FollowupSpec } from '../../spec/emitSpec'
import type { Pattern } from '../predicate'
import { Rule } from './base'
import type { DispatchEngine } from './dispatch'

export class EmitRule extends Rule {
    constructor(
        on: Pattern,
        followups: FollowupSpec[],
        private readonly emit: EmitSpec
    ) {
        super(on, followups)
    }
    produce(scope: Scope, engine: DispatchEngine, allowDrop: boolean): CompatMessage[] {
        const message = engine.coercer.buildMessage(this.emit, scope, allowDrop)
        return message ? [message] : []
    }
}
