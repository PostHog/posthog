import './PersonHeader.scss'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { ProfilePicture, ProfilePictureProps } from 'lib/lemon-ui/ProfilePicture'
import { teamLogic } from 'scenes/teamLogic'
import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import { midEllipsis } from 'lib/utils'
import clsx from 'clsx'
import { Popover } from 'lib/lemon-ui/Popover'
import { PersonPreview } from './PersonPreview'
import { useState } from 'react'
import { router } from 'kea-router'

type PersonPropType =
    | { properties?: Record<string, any>; distinct_ids?: string[]; distinct_id?: never }
    | { properties?: Record<string, any>; distinct_ids?: never; distinct_id?: string }

export interface PersonHeaderProps {
    person?: PersonPropType | null
    withIcon?: boolean | ProfilePictureProps['size']
    noLink?: boolean
    noEllipsis?: boolean
    noPopover?: boolean
}

/** Very permissive email format. */
const EMAIL_REGEX = /.+@.+\..+/i
/** Very rough UUID format. It's loose around length, because the posthog-js UUID util returns non-normative IDs. */
const BROWSER_ANON_ID_REGEX = /^(?:[a-fA-F0-9]+-){4}[a-fA-F0-9]+$/i
/** Score distinct IDs for display: UUID-like (i.e. anon ID) gets 0, custom format gets 1, email-like gets 2. */
function scoreDistinctId(id: string): number {
    if (EMAIL_REGEX.test(id)) {
        return 2
    }
    if (BROWSER_ANON_ID_REGEX.test(id) && id.length > 36) {
        // posthog-js IDs have the shape of UUIDs but are longer
        return 0
    }
    return 1
}

export function asDisplay(person: PersonPropType | null | undefined, maxLength?: number): string {
    if (!person) {
        return 'Unknown'
    }
    const team = teamLogic.findMounted()?.values?.currentTeam

    // Sync the logic below with the plugin server `getPersonDetails`
    const personDisplayNameProperties = team?.person_display_name_properties ?? PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
    const customPropertyKey = personDisplayNameProperties.find((x) => person.properties?.[x])
    const propertyIdentifier = customPropertyKey ? person.properties?.[customPropertyKey] : undefined

    const customIdentifier: string =
        typeof propertyIdentifier !== 'string' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

    const display: string | undefined = (
        customIdentifier ||
        person.distinct_id ||
        (person.distinct_ids
            ? person.distinct_ids.slice().sort((a, b) => scoreDistinctId(b) - scoreDistinctId(a))[0]
            : undefined)
    )?.trim()

    return display ? midEllipsis(display, maxLength || 40) : 'Person without ID'
}

export const asLink = (person?: PersonPropType | null): string | undefined =>
    person?.distinct_id
        ? urls.person(person.distinct_id)
        : person?.distinct_ids?.length
        ? urls.person(person.distinct_ids[0])
        : undefined

export function PersonHeader({ person, withIcon, noEllipsis, noPopover, noLink }: PersonHeaderProps): JSX.Element {
    const href = asLink(person)
    const display = asDisplay(person)
    const [visible, setVisible] = useState(false)

    let content = (
        <div className="flex items-center">
            {withIcon && (
                <ProfilePicture
                    name={display}
                    email={person?.properties?.email}
                    size={typeof withIcon === 'string' ? withIcon : 'md'}
                />
            )}
            <span className={clsx('ph-no-capture', !noEllipsis && 'text-ellipsis')}>{display}</span>
        </div>
    )

    content = (
        <div
            className="person-header"
            onClick={
                !noPopover
                    ? () => {
                          if (visible && href) {
                              router.actions.push(href)
                          } else {
                              setVisible(true)
                          }
                      }
                    : undefined
            }
        >
            {noLink || !href ? (
                content
            ) : (
                <Link
                    to={href}
                    onClick={(e) => {
                        if (!noPopover) {
                            e.preventDefault()
                            return
                        }
                    }}
                    data-attr={`goto-person-email-${person?.distinct_id || person?.distinct_ids?.[0]}`}
                >
                    {content}
                </Link>
            )}
        </div>
    )

    content = noPopover ? (
        content
    ) : (
        <Popover
            overlay={<PersonPreview distinctId={person?.distinct_id || person?.distinct_ids?.[0]} />}
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="right"
            fallbackPlacements={['bottom', 'top']}
        >
            {content}
        </Popover>
    )

    return content
}
