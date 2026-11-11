import { useValues } from 'kea'

import { PropertyDefinitionTypeNameEnumApi } from '~/generated/core/api.schemas'
import type { PropertyUsageEntryApi } from '~/generated/core/api.schemas'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'

import { DefinitionUsageSection } from './DefinitionUsageSection'
import { propertyUsageLogic } from './propertyUsageLogic'
import { PropertyValueCountsSection } from './PropertyValueCountsSection'

export function PropertyDefinitionUsage({ entry }: { entry: PropertyUsageEntryApi }): JSX.Element {
    const { queryCount, queryCountLoading, queryCountFailed } = useValues(propertyUsageLogic({ entry }))

    return (
        <>
            <DefinitionUsageSection
                queryCount={queryCount}
                queryCountLoading={queryCountLoading}
                queryCountFailed={queryCountFailed}
                insightsLogicProps={{ definitionType: 'property', name: entry.name }}
            />
            {/* Session properties are computed from events at query time, so no sent values are recorded for them. */}
            {entry.type !== PropertyDefinitionTypeNameEnumApi.Session && (
                <>
                    <SceneDivider />
                    <PropertyValueCountsSection entry={entry} />
                </>
            )}
        </>
    )
}
