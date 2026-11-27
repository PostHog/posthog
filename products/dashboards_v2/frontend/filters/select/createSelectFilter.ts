import { type FilterDefinition, defineFilter } from '../filterDefinition'
import { SelectFilter } from './SelectFilter'
import {
    type SelectFilterConfig,
    type SelectFilterField,
    type SelectFilterValue,
    selectFilterSpec,
} from './selectFilterSpec'

export function createSelectFilter(fields: SelectFilterField[]): FilterDefinition {
    return defineFilter<SelectFilterConfig, SelectFilterValue>({ ...selectFilterSpec(fields), Control: SelectFilter })
}
