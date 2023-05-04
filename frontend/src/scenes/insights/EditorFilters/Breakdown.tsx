import { useActions } from 'kea'
import { EditorFilterProps } from '~/types'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'

export function Breakdown({ filters }: EditorFilterProps): JSX.Element {
    const { setFiltersMerge } = useActions(insightLogic)

    return <TaxonomicBreakdownFilter filters={filters} setFilters={setFiltersMerge} />
}
