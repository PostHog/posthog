import { hasField, readField } from '../../paths'
import { Predicate } from './base'

export class Pattern {
    constructor(private readonly fields: Record<string, Predicate>) {}

    matches(input: unknown): boolean {
        for (const [field, predicate] of Object.entries(this.fields)) {
            const value = field === '$' ? input : readField(input, field)
            const present = field === '$' ? input !== undefined : hasField(input, field)
            if (!predicate.test(value, present)) {
                return false
            }
        }
        return true
    }
}
