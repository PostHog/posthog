import { Predicate } from './base'

export class ExistsPredicate extends Predicate {
    constructor(private readonly shouldExist: boolean) {
        super()
    }
    test(_value: unknown, present: boolean): boolean {
        return present === this.shouldExist
    }
}
