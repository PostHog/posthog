import { LemonInput, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { parseAliasToReadable } from 'lib/components/PathCleanFilters/PathCleanFilterItem'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'
import { useState } from 'react'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, InsightType } from '~/types'

export function PathCleaningFiltersConfig(): JSX.Element | null {
    const [testValue, setTestValue] = useState('')

    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)
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

    const cleanedTestPath =
        currentTeam.path_cleaning_filters?.reduce((text, filter) => {
            return text.replace(new RegExp(filter.regex ?? ''), filter.alias ?? '')
        }, testValue) ?? ''
    const readableTestPath = parseAliasToReadable(cleanedTestPath)

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
            <p>These will be applied in order. You can reorder them by dragging and dropping.</p>
            <p>
                <b>
                    Rules that you set here will be applied before wildcarding and other regex replacement if path
                    cleaning is switched on in Product and Web Analytics.
                </b>
            </p>
            <PathCleanFilters
                filters={currentTeam.path_cleaning_filters}
                setFilters={(filters) => updateCurrentTeam({ path_cleaning_filters: filters })}
            />

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
        </>
    )
}
