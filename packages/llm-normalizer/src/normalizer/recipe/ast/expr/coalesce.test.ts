import { Scope } from '../../scope'
import { ArrayExpr } from './array'
import { CoalesceExpr } from './coalesce'
import { LiteralExpr } from './literal'

const coalesce = (...values: unknown[]): CoalesceExpr =>
    new CoalesceExpr(new ArrayExpr(values.map((v) => new LiteralExpr(v))))

describe('CoalesceExpr', () => {
    const scope = Scope.forNode({}, 'user')

    it('returns the first non-nullish value', () => {
        expect(coalesce(null, undefined, 'chosen', 'later').eval(scope)).toBe('chosen')
    })

    it('skips nullish values but keeps falsy ones like 0 and empty string', () => {
        expect(coalesce(null, 0, 'later').eval(scope)).toBe(0)
        expect(coalesce(undefined, '', 'later').eval(scope)).toBe('')
    })

    it('returns undefined when every candidate is nullish', () => {
        expect(coalesce(null, undefined).eval(scope)).toBeUndefined()
    })
})
