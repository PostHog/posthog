import { useActions, useValues } from 'kea'
import { LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import { EditorFilterProps } from '~/types'

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
