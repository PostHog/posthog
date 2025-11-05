import './PersonDisplay.scss'

import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import { ProfilePictureProps } from 'lib/lemon-ui/ProfilePicture'
import { midEllipsis } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { HogQLQueryString, hogql } from '~/queries/utils'

export type PersonPropType =
    | { properties?: Record<string, any>; distinct_ids?: string[]; distinct_id?: never; id?: never }
    | { properties?: Record<string, any>; distinct_ids?: never; distinct_id?: string; id?: never }
    | { properties?: Record<string, any>; distinct_ids?: string[]; distinct_id?: string; id: string }

export interface PersonDisplayProps {
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

    return display ? midEllipsis(display, maxLength || 40) : 'Anonymous'
}

export const asLink = (person?: PersonPropType | null): string | undefined =>
    person?.distinct_id
        ? urls.personByDistinctId(person.distinct_id)
        : person?.distinct_ids?.length
          ? urls.personByDistinctId(person.distinct_ids[0])
          : person?.id
            ? urls.personByUUID(person.id)
            : undefined

export const getHogqlQueryStringForPersonId = (): HogQLQueryString => {
    return hogql`SELECT
                    id,
                    groupArray(101)(pdi2.distinct_id) as distinct_ids,
                    properties,
                    is_identified,
                    created_at
                FROM persons
                LEFT JOIN (
                    SELECT
                        pdi2.distinct_id,
                        argMax(pdi2.person_id, pdi2.version) AS person_id
                    FROM raw_person_distinct_ids pdi2
                    WHERE pdi2.distinct_id IN (
                            SELECT distinct_id
                            FROM raw_person_distinct_ids
                            WHERE person_id = {id}
                        )
                    GROUP BY pdi2.distinct_id
                    HAVING argMax(pdi2.is_deleted, pdi2.version) = 0
                        AND argMax(pdi2.person_id, pdi2.version) = {id}
                ) AS pdi2 ON pdi2.person_id = persons.id
                WHERE persons.id = {id}
                GROUP BY id, properties, is_identified, created_at`
}
