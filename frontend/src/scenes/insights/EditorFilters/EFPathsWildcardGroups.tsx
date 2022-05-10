import React from 'react'
import { useValues, useActions } from 'kea'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { Select } from 'antd'
import { EditorFilterProps } from '~/types'

export function EFPathsWildcardGroups({ insightProps }: EditorFilterProps): JSX.Element {
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    return (
        <Select
            mode="tags"
            style={{ width: '100%' }}
            onChange={(path_groupings) => setFilter({ path_groupings })}
            tokenSeparators={[',']}
            value={filter.path_groupings || []}
        />
    )
}
