import type { Rule } from '../ast/rule'

export interface Recipe {
    id: string
    rules: Rule[]
}
