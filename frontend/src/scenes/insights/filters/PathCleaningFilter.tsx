import { useActions, useValues } from 'kea'

import { PathCleaningControls } from 'lib/components/PathCleanFilters/PathCleaningControls'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import { EditorFilterProps } from '~/types'

export function PathCleaningFilter({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { localPathCleaningFilters, pathReplacements } = pathsFilter || {}

    return (
        <PathCleaningControls
            localFilters={localPathCleaningFilters || []}
            setLocalFilters={(localPathCleaningFilters) => updateInsightFilter({ localPathCleaningFilters })}
            applyGlobal={!!pathReplacements}
            setApplyGlobal={(pathReplacements) => updateInsightFilter({ pathReplacements })}
        />
    )
}
