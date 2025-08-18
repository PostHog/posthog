import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonInput, Link } from '@posthog/lemon-ui'

import { PathCleanFilterAddItemButton } from 'lib/components/PathCleanFilters/PathCleanFilterAddItemButton'
import { parseAliasToReadable } from 'lib/components/PathCleanFilters/PathCleanFilterItem'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'
import { PathCleanFiltersTable } from 'lib/components/PathCleanFilters/PathCleanFiltersTable'
import { PathCleaningRulesDebugger } from 'lib/components/PathCleanFilters/PathCleaningRulesDebugger'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isValidRegexp } from 'lib/utils/regexp'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, InsightType, PathCleaningFilter } from '~/types'

const cleanPathWithRegexes = (path: string, filters: PathCleaningFilter[]): string => {
    return filters.reduce((text, filter) => {
        // If for some reason we don't have a valid RegExp, don't attempt to clean the path
        if (!isValidRegexp(filter.regex ?? '')) {
            return text
        }

        return text.replace(new RegExp(filter.regex ?? '', 'gi'), filter.alias ?? '')
    }, path)
}

export function PathCleaningFiltersConfig(): JSX.Element | null {
    const [testValue, setTestValue] = useState('')

    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)

    if (!currentTeam) {
        return null
    }

    if (!hasAdvancedPaths) {
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

    const cleanedTestPath = cleanPathWithRegexes(testValue, currentTeam.path_cleaning_filters ?? [])
    const readableTestPath = parseAliasToReadable(cleanedTestPath)

    const useTableUI = featureFlags[FEATURE_FLAGS.PATH_CLEANING_FILTER_TABLE_UI]

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

    return (
        <>
            <p>
                Make your <Link to={INSIGHT_TYPE_URLS[InsightType.PATHS]}>Paths</Link> clearer by aliasing one or
                multiple URLs.{' '}
                <i>
                    Example: <code>http://tenant-one.mydomain.com/accounts</code> and{' '}
                    <code>http://tenant-two.mydomain.com/accounts</code> can become a single <code>/accounts</code>{' '}
                    path.
                </i>
            </p>
            <p>
                You can check{' '}
                <Link to="https://posthog.com/docs/product-analytics/paths#path-cleaning-rules">
                    our path cleaning rules documentation
                </Link>{' '}
                to learn more about it.
            </p>
            <p>
                Each rule is composed of an alias and a regex pattern. Any pattern in a URL or event name that matches
                the regex will be replaced with the alias. Rules are applied in the order that they're listed.
            </p>
            <p>
                These will be applied in order, so make sure to put the most specific rules first and remember that
                subsequent rules will receive the result of the previous one, not the original path. You can reorder
                them by dragging and dropping.
            </p>
            <p>
                <b>
                    Rules that you set here will be applied before wildcarding and other regex replacement if path
                    cleaning is switched on in Product and Web Analytics.
                </b>
            </p>

            {useTableUI ? (
                <div className="flex flex-col gap-4">
                    <PathCleanFiltersTable
                        filters={currentTeam.path_cleaning_filters || []}
                        setFilters={updateFilters}
                    />
                    <div>
                        <PathCleanFilterAddItemButton onAdd={onAddFilter} />
                    </div>
                </div>
            ) : (
                <PathCleanFilters filters={currentTeam.path_cleaning_filters} setFilters={updateFilters} />
            )}

            <p className="mt-4">Wanna test what your cleaned path will look like? Try them out here.</p>
            <div className="flex flex-col sm:flex-row gap-2 items-center justify-center">
                <LemonInput
                    value={testValue}
                    onChange={setTestValue}
                    placeholder="Enter a path to test"
                    size="medium"
                    className="flex-1"
                />
                --&gt;
                <span className="inline-flex items-center justify-start p-2 font-mono text-xs flex-1 border rounded min-h-10">
                    {readableTestPath}
                </span>
            </div>

            {useTableUI && (
                <PathCleaningRulesDebugger
                    testPath={testValue}
                    filters={currentTeam.path_cleaning_filters ?? []}
                    finalResult={readableTestPath}
                />
            )}
        </>
    )
}
