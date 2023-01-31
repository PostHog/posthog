import { useValues, useActions } from 'kea'

import { pathsLogic } from 'scenes/paths/pathsLogic'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import { EditorFilterProps, PathsFilterType, QueryEditorFilterProps } from '~/types'
import { LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'

export function PathsWildcardGroupsDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    return <PathsWildcardGroupsComponent setFilter={updateInsightFilter} {...insightFilter} />
}

export function PathsWildcardGroups({ insightProps }: EditorFilterProps): JSX.Element {
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    return <PathsWildcardGroupsComponent setFilter={setFilter} {...filter} />
}

type PathsWildcardGroupsComponentProps = {
    setFilter: (filter: PathsFilterType) => void
} & PathsFilterType

export function PathsWildcardGroupsComponent({
    setFilter,
    path_groupings,
}: PathsWildcardGroupsComponentProps): JSX.Element {
    return (
        <LemonSelectMultiple
            onChange={(path_groupings) => setFilter({ path_groupings })}
            value={path_groupings || []}
            filterOption={false}
            mode="multiple-custom"
        />
    )
}
