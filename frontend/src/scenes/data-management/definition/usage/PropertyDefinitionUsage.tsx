import { useValues } from 'kea'

import type { PropertyUsageEntryApi } from '~/generated/core/api.schemas'

import { DefinitionUsageSection } from './DefinitionUsageSection'
import { propertyUsageLogic } from './propertyUsageLogic'

export function PropertyDefinitionUsage({ entry }: { entry: PropertyUsageEntryApi }): JSX.Element {
    const { queryCount, queryCountLoading, queryCountFailed } = useValues(propertyUsageLogic({ entry }))

    return (
        <DefinitionUsageSection
            queryCount={queryCount}
            queryCountLoading={queryCountLoading}
            queryCountFailed={queryCountFailed}
            insightsLogicProps={{ definitionType: 'property', name: entry.name }}
        />
    )
}
