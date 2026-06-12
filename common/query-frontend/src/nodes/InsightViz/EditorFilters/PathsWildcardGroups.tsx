import { useActions, useValues } from 'kea'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { pathsDataLogic } from '@posthog/query-frontend/nodes/PathsQuery/pathsDataLogic'

import { EditorFilterProps } from '~/types'

export function PathsWildcardGroups({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    return (
        <LemonInputSelect
            onChange={(pathGroupings: string[]) => updateInsightFilter({ pathGroupings })}
            value={pathsFilter?.pathGroupings || []}
            disableFiltering
            mode="multiple"
            allowCustomValues
        />
    )
}
