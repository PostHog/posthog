import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { PersonType } from '~/types'

interface LivePersonDrillDownRowProps {
    person: PersonType
}

const pickSecondaryProperty = (person: PersonType): { key: string; value: string } | null => {
    const candidates = ['email', '$browser', '$os', '$geoip_country_code']
    for (const key of candidates) {
        const raw = person.properties?.[key]
        if (typeof raw === 'string' && raw.length > 0) {
            return { key, value: raw }
        }
    }
    return null
}

export const LivePersonDrillDownRow = ({ person }: LivePersonDrillDownRowProps): JSX.Element => {
    const distinctId = person.distinct_ids?.[0]
    const secondary = pickSecondaryProperty(person)
    const href = distinctId ? urls.personByDistinctId(distinctId) : undefined

    return (
        <Link
            to={href}
            subtle
            className="flex items-center gap-3 px-2 py-2 -mx-2 rounded hover:bg-bg-3000"
            data-attr="live-person-drilldown-row"
        >
            <PersonDisplay person={person} withIcon noPopover noLink />
            {secondary && (
                <span className="flex-1 min-w-0 text-xs text-muted truncate ph-no-capture">
                    {secondary.key === 'email' ? secondary.value : `${secondary.key}: ${secondary.value}`}
                </span>
            )}
            {person.last_seen_at && (
                <span className="text-xs text-muted shrink-0 ml-auto">
                    <TZLabel time={person.last_seen_at} />
                </span>
            )}
        </Link>
    )
}
