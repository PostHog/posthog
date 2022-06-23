import React from 'react'
import { useValues, useActions } from 'kea'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { EditorFilterProps } from '~/types'
import { LemonSelectSearch } from 'lib/components/LemonSelectSearch/LemonSelectSearch'

export function EFPathsWildcardGroups({ insightProps }: EditorFilterProps): JSX.Element {
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    return (
        <>
            <LemonSelectSearch
                onChange={(path_groupings) => setFilter({ path_groupings })}
                value={filter.path_groupings || []}
                filterOption={false}
                mode="multiple-custom"
            />
        </>
    )
}
