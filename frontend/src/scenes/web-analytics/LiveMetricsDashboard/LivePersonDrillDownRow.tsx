import { IconPlay } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { PersonsTabType, PersonType } from '~/types'

interface LivePersonDrillDownRowProps {
    person: PersonType
    recordingCount?: number
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

const recordingsUrlForPerson = (distinctId: string): string =>
    `${urls.personByDistinctId(distinctId)}#activeTab=${PersonsTabType.SESSION_RECORDINGS}`

export const LivePersonDrillDownRow = ({ person, recordingCount }: LivePersonDrillDownRowProps): JSX.Element => {
    const distinctId = person.distinct_ids?.[0]
    const secondary = pickSecondaryProperty(person)
    const href = distinctId ? urls.personByDistinctId(distinctId) : undefined

    return (
        <div className="flex items-center gap-3" data-attr="live-person-drilldown-row">
            <Link
                to={href}
                subtle
                className="flex items-center gap-3 min-w-0 flex-1 px-2 py-2 -mx-2 rounded hover:bg-bg-3000"
            >
                <PersonDisplay person={person} withIcon noPopover noLink />
                {secondary && (
                    <span className="min-w-0 text-xs text-muted truncate ph-no-capture">
                        {secondary.key === 'email' ? secondary.value : `${secondary.key}: ${secondary.value}`}
                    </span>
                )}
            </Link>
            {recordingCount && recordingCount > 0 && distinctId && (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconPlay />}
                    to={recordingsUrlForPerson(distinctId)}
                    targetBlank
                    tooltip={`Watch ${pluralize(recordingCount, 'recording')} from the last 30 minutes`}
                    data-attr="live-person-drilldown-row-watch"
                >
                    {recordingCount.toLocaleString()}
                </LemonButton>
            )}
            {person.last_seen_at && (
                <span className="text-xs text-muted shrink-0">
                    <TZLabel time={person.last_seen_at} />
                </span>
            )}
        </div>
    )
}
