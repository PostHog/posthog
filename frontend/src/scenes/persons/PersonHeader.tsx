import './PersonHeader.scss'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { teamLogic } from 'scenes/teamLogic'
import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import { midEllipsis } from 'lib/utils'
import clsx from 'clsx'

type PersonPropType =
    | { properties?: Record<string, any>; distinct_ids?: string[]; distinct_id?: never }
    | { properties?: Record<string, any>; distinct_ids?: never; distinct_id?: string }

export interface PersonHeaderProps {
    person?: PersonPropType | null
    withIcon?: boolean
    noLink?: boolean
    noEllipsis?: boolean
}

/** Very permissive email regex. */
const EMAIL_REGEX = /.+@.+\..+/i

export function asDisplay(person: PersonPropType | null | undefined, maxLength?: number): string {
    if (!person) {
        return 'Unknown'
    }
    const team = teamLogic.findMounted()?.values?.currentTeam
    const personDisplayNameProperties = team?.person_display_name_properties ?? PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES

    const customPropertyKey = personDisplayNameProperties.find((x) => person.properties?.[x])
    const propertyIdentifier = customPropertyKey ? person.properties?.[customPropertyKey] : undefined

    const customIdentifier: string =
        typeof propertyIdentifier !== 'string' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

    const display: string | undefined = (
        customIdentifier ||
        person.distinct_id ||
        (person.distinct_ids && // If there are multiple IDs, prefer the first one that has email characteristics
            (person.distinct_ids.find((id) => EMAIL_REGEX.test(id)) || person.distinct_ids?.[0]))
    )?.trim()

    return display ? midEllipsis(display, maxLength || 40) : 'Person without ID'
}

export const asLink = (person?: PersonPropType | null): string | undefined =>
    person?.distinct_id
        ? urls.person(person.distinct_id)
        : person?.distinct_ids?.length
        ? urls.person(person.distinct_ids[0])
        : undefined

export function PersonHeader(props: PersonHeaderProps): JSX.Element {
    const href = asLink(props.person)
    const display = asDisplay(props.person)

    const content = (
        <div className="flex items-center">
            {props.withIcon && <ProfilePicture name={display} size="md" />}
            <span className={clsx('ph-no-capture', !props.noEllipsis && 'text-ellipsis')}>{display}</span>
        </div>
    )

    return (
        <div className="person-header">
            {props.noLink || !href ? (
                content
            ) : (
                <Link
                    to={href}
                    data-attr={`goto-person-email-${props.person?.distinct_id || props.person?.distinct_ids?.[0]}`}
                >
                    {content}
                </Link>
            )}
        </div>
    )
}
