import { OrderBy } from './OrderBy'
import { PriorityFilter } from './Priority'
import { FiltersRoot } from './Root'
import { StatusFilter } from './Status'

export const ZendeskTicketsFilters = {
    Root: FiltersRoot,
    OrderBy: OrderBy,
    Priority: PriorityFilter,
    Status: StatusFilter,
}
