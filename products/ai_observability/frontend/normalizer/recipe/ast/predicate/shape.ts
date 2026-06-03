import { Predicate } from './base'
import { Pattern } from './pattern'

export class ShapePredicate extends Predicate {
    constructor(private readonly nested: Pattern) {
        super()
    }
    test(value: unknown, present: boolean): boolean {
        if (!present || !value || typeof value !== 'object') {
            return false
        }
        return this.nested.matches(value)
    }
}
