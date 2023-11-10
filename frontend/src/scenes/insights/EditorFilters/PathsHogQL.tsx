import { useValues, useActions } from 'kea'
import { EditorFilterProps } from '~/types'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { taxonomicEventFilterToHogQL } from '~/queries/utils'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

export function PathsHogQL({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    return (
        <TaxonomicPopover
            groupType={TaxonomicFilterGroupType.HogQLExpression}
            value={pathsFilter?.paths_hogql_expression || 'event'}
            data-attr="paths-hogql-expression"
            type="secondary"
            fullWidth
            onChange={(v, g) => {
                const hogQl = taxonomicEventFilterToHogQL(g, v)
                if (hogQl) {
                    updateInsightFilter({ paths_hogql_expression: hogQl })
                }
            }}
            groupTypes={[TaxonomicFilterGroupType.HogQLExpression]}
        />
    )
}
