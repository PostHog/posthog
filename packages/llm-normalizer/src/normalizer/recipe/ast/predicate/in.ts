import { Predicate } from './base'

export class InPredicate extends Predicate {
    constructor(private readonly values: unknown[]) {
        super()
    }
    test(value: unknown, present: boolean): boolean {
        return present && this.values.includes(value)
    }
}
