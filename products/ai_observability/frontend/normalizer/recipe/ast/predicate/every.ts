import { Predicate } from './base'

export class EveryPredicate extends Predicate {
    constructor(private readonly element: Predicate) {
        super()
    }
    test(value: unknown, present: boolean): boolean {
        if (!present || !Array.isArray(value) || value.length === 0) {
            return false
        }
        return value.every((item) => this.element.test(item, item !== undefined))
    }
}
