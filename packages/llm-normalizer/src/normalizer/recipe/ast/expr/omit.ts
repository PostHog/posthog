import { Scope } from '../../scope'
import { Expr } from './base'

export class OmitExpr extends Expr {
    constructor(
        private readonly from: Expr,
        private readonly keys: Expr | null
    ) {
        super()
    }
    eval(scope: Scope): unknown {
        const from = this.from.eval(scope)
        if (!from || typeof from !== 'object' || Array.isArray(from)) {
            return {}
        }
        const rawKeys = this.keys ? this.keys.eval(scope) : undefined
        const keys = Array.isArray(rawKeys) ? rawKeys.filter((k): k is string => typeof k === 'string') : []
        const out: Record<string, unknown> = { ...(from as Record<string, unknown>) }
        for (const k of keys) {
            delete out[k]
        }
        return out
    }
}
