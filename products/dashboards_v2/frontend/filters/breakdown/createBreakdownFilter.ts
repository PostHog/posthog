import { type FilterDefinition, defineFilter } from '../filterDefinition'
import { BreakdownFilter } from './BreakdownFilter'
import {
    type BreakdownFilterConfig,
    type BreakdownFilterValue,
    type BreakdownOption,
    breakdownFilterSpec,
} from './breakdownFilterSpec'

export function createBreakdownFilter(options: BreakdownOption[]): FilterDefinition {
    return defineFilter<BreakdownFilterConfig, BreakdownFilterValue>({
        ...breakdownFilterSpec(options),
        Control: BreakdownFilter,
    })
}
