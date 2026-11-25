import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonInput, Link } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { PathCleanFilterAddItemButton } from 'lib/components/PathCleanFilters/PathCleanFilterAddItemButton'
import { parseAliasToReadable } from 'lib/components/PathCleanFilters/PathCleanFilterItem'
import { PathCleanFiltersTable } from 'lib/components/PathCleanFilters/PathCleanFiltersTable'
import { PathCleaningRulesDebugger } from 'lib/components/PathCleanFilters/PathCleaningRulesDebugger'
import { applyPathCleaning } from 'lib/components/PathCleanFilters/pathCleaningUtils'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { PathCleaningSuggestionsBanner } from 'scenes/settings/environment/PathCleaningSuggestionsBanner'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, PathCleaningFilter } from '~/types'

import { QuillPathCleaningFiltersConfig } from './QuillPathCleaningFiltersConfig'

export function PathCleaningFiltersConfig(): JSX.Element | null {
    const [testValue, setTestValue] = useState('')

    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!currentTeam) {
        return null
    }

    if (!hasAdvancedPaths) {
        if (todayRailNav) {
            return (
                <Text size="xs" render={<p className="m-0" />}>
                    Advanced path cleaning is a premium feature. Check{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to="https://posthog.com/docs/product-analytics/paths#path-cleaning-rules"
                                target="_blank"
                            />
                        }
                    >
                        our path cleaning rules documentation
                    </Button>{' '}
                    to learn more about it.
                </Text>
            )
        }

        return (
            <p>
                Advanced path cleaning is a premium feature. Check{' '}
                <Link to="https://posthog.com/docs/product-analytics/paths#path-cleaning-rules">
                    our path cleaning rules documentation
                </Link>{' '}
                to learn more about it.
            </p>
        )
    }

    const cleanedTestPath = applyPathCleaning(testValue, currentTeam.path_cleaning_filters ?? [])
    const readableTestPath = parseAliasToReadable(cleanedTestPath)

    const updateFilters = (filters: PathCleaningFilter[]): void => {
        updateCurrentTeam({ path_cleaning_filters: filters })
    }

    const onAddFilter = (filter: PathCleaningFilter): void => {
        const filterWithOrder = {
            ...filter,
            order: (currentTeam.path_cleaning_filters || []).length,
        }
        updateFilters([...(currentTeam.path_cleaning_filters || []), filterWithOrder])
    }

    if (todayRailNav) {
        return (
            <QuillPathCleaningFiltersConfig
                filters={currentTeam.path_cleaning_filters || []}
                testValue={testValue}
                onTestValueChange={setTestValue}
                readableTestPath={readableTestPath}
                restrictedReason={restrictedReason}
                onFiltersChange={updateFilters}
                onAddFilter={onAddFilter}
            />
        )
    }

    return (
        <>
            <PathCleaningSuggestionsBanner />
            <div className="flex flex-col gap-4">
                <PathCleanFiltersTable filters={currentTeam.path_cleaning_filters || []} setFilters={updateFilters} />
                <div>
                    <PathCleanFilterAddItemButton onAdd={onAddFilter} />
                </div>
            </div>

            <p className="mt-4">Wanna test what your cleaned path will look like? Try them out here.</p>
            <div className="flex flex-col sm:flex-row gap-2 items-center justify-center">
                <LemonInput
                    value={testValue}
                    onChange={setTestValue}
                    placeholder="Enter a path to test"
                    size="medium"
                    className="flex-1"
                    disabledReason={restrictedReason}
                />
                <IconArrowRight />
                <span className="inline-flex items-center justify-start p-2 font-mono text-xs flex-1 border rounded min-h-10">
                    {readableTestPath}
                </span>
            </div>

            <PathCleaningRulesDebugger
                testPath={testValue}
                filters={currentTeam.path_cleaning_filters ?? []}
                finalResult={readableTestPath}
            />
        </>
    )
}
