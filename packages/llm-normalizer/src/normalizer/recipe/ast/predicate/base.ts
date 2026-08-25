export abstract class Predicate {
    abstract test(value: unknown, present: boolean): boolean
}
