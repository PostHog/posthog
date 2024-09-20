import { Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PathCleanFilters } from 'lib/components/PathCleanFilters/PathCleanFilters'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, InsightType } from '~/types'

export function PathCleaningFiltersConfig(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)

    if (!currentTeam) {
        return null
    }

    if (!hasAdvancedPaths) {
        return <p>Advanced path cleaning is a premium feature.</p>
    }

    return (
        <>
            <p>
                Make your <Link to={urls.insightNew(InsightType.PATHS)}>Paths</Link> clearer by aliasing one or multiple
                URLs.{' '}
                <i>
                    Example: <code>http://tenant-one.mydomain.com/accounts</code> and{' '}
                    <code>http://tenant-two.mydomain.com/accounts</code> can become a single <code>/accounts</code>{' '}
                    path.
                </i>
            </p>
            <p>
                Each rule is composed of an alias and a regex pattern. Any pattern in a URL or event name that matches
                the regex will be replaced with the alias. Rules are applied in the order that they're listed.
            </p>
            <p>
                <b>
                    Rules that you set here will be applied before wildcarding and other regex replacement if the toggle
                    is switched on.
                </b>
            </p>
            <PathCleanFilters
                filters={currentTeam.path_cleaning_filters}
                setFilters={(filters) => {
                    updateCurrentTeam({ path_cleaning_filters: filters })
                }}
            />
        </>
    )
}
