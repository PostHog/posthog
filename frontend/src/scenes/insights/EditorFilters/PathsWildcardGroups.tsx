import { useValues, useActions } from 'kea'

import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import { EditorFilterProps } from '~/types'
import { LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'

export function PathsWildcardGroups({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    return (
        <LemonSelectMultiple
            onChange={(path_groupings: string[]) => updateInsightFilter({ path_groupings })}
            value={pathsFilter?.path_groupings || []}
            filterOption={false}
            mode="multiple-custom"
        />
    )
}
