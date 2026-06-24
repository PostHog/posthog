import { Predicate } from './base'

export class EqualsPredicate extends Predicate {
    constructor(private readonly expected: unknown) {
        super()
    }
    test(value: unknown, present: boolean): boolean {
        return present && value === this.expected
    }
}
