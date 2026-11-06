import { Predicate } from './base'
import { matchesType, TypeName } from './typeName'

export class IsPredicate extends Predicate {
    constructor(private readonly types: TypeName[]) {
        super()
    }
    test(value: unknown, present: boolean): boolean {
        return present && this.types.some((type) => matchesType(value, type))
    }
}
