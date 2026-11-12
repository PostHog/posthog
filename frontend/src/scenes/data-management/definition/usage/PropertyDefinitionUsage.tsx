import { useValues } from 'kea'

import { type PropertyUsageEntryApi, PropertyDefinitionTypeNameEnumApi } from '~/generated/core/api.schemas'

import { DefinitionUsageSection } from './DefinitionUsageSection'
import { PropertyEventVolumeCard } from './PropertyEventVolumeCard'
import { propertyUsageLogic } from './propertyUsageLogic'

export function PropertyDefinitionUsage({ entry }: { entry: PropertyUsageEntryApi }): JSX.Element {
    const { queryUsage, queryUsageLoading, queryUsageFailed } = useValues(propertyUsageLogic({ entry }))

    return (
        <DefinitionUsageSection
            queryUsage={queryUsage}
            queryUsageLoading={queryUsageLoading}
            queryUsageFailed={queryUsageFailed}
            insightsLogicProps={{ definitionType: 'property', name: entry.name }}
            eventVolumeCard={
                entry.type === PropertyDefinitionTypeNameEnumApi.Event ? (
                    <PropertyEventVolumeCard propertyName={entry.name} />
                ) : undefined
            }
        />
    )
}
