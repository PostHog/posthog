import { useValues, useActions } from 'kea'

import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import { QueryEditorFilterProps } from '~/types'
import { LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'
import { PathsFilter } from '~/queries/schema'

export function PathsWildcardGroups({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    return (
        <LemonSelectMultiple
            onChange={(path_groupings: string[]) => updateInsightFilter({ path_groupings })}
            value={(insightFilter as PathsFilter)?.path_groupings || []}
            filterOption={false}
            mode="multiple-custom"
        />
    )
}
