import { IconPeople } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { TestAccountFilteringSource } from './insightDetailsFilterOverrides'

const EXPLANATION: Record<TestAccountFilteringSource, string> = {
    insight:
        'This insight counts internal and test users. Turn on "Filter out internal and test users" on the insight to leave them out.',
    dashboard: 'This dashboard counts internal and test users in every insight.',
    tile: 'This tile counts internal and test users, overriding the insight.',
}

export function IncludesTestUsersNotice({ source }: { source: TestAccountFilteringSource }): JSX.Element {
    return (
        <Tooltip title={EXPLANATION[source]}>
            <div className="flex items-center gap-1 text-muted-alt">
                <IconPeople /> Includes test users
            </div>
        </Tooltip>
    )
}
