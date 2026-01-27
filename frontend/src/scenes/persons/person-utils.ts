import './PersonDisplay.scss'

import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import { NUM_LETTERMARK_STYLES } from 'lib/lemon-ui/Lettermark/Lettermark'
import { ProfilePictureProps } from 'lib/lemon-ui/ProfilePicture'
import { isUUIDLike, midEllipsis } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { HogQLQueryString, hogql } from '~/queries/utils'

/**
 * Generates a stable color index from a string using djb2 hash.
 * Used for consistent avatar colors based on person identifiers.
 */
function hashStringToColorIndex(str: string): number {
    let hash = 5381
    for (let i = 0; i < str.length; i++) {
        hash = (hash * 33) ^ str.charCodeAt(i)
    }
    return Math.abs(hash) % NUM_LETTERMARK_STYLES
}

/**
 * Returns a stable color index for a person based on their identifier.
 * Uses distinct_id (or first of distinct_ids) to generate consistent colors.
 */
export function getPersonColorIndex(person: PersonPropType | null | undefined): number | undefined {
    if (!person) {
        return undefined
    }
    const identifier = person.distinct_id || person.distinct_ids?.[0]
    if (!identifier) {
        return undefined
    }
    return hashStringToColorIndex(identifier)
}

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

/**
 * Returns a human-friendly display name for a Person object.
 *
 * Resolution order:
 * 1. A custom display property defined by the team
 * 2. `person.distinct_id`
 * 3. The highest-priority ID from `person.distinct_ids`
 *
 * If `truncateIdUUID` is enabled and the resolved value looks UUID-like
 * (8-4-4-4-12 hex format), the string is truncated via `midEllipsis` to
 * 22 characters (or `maxLength` if provided).
 *
 * @param person - The Person object to format.
 * @param maxLength - Optional maximum length for non-UUID display values. Defaults to 40.
 * @param truncateIdUUID - Whether to truncate UUID-like identifiers. Defaults to false.
 * @returns A formatted display string such as an email, name, or truncated ID.
 */
export function asDisplay(
    person: PersonPropType | null | undefined,
    maxLength?: number,
    truncateIdUUID?: boolean
): string {
    if (!person) {
        return 'Unknown'
    }
    const team = teamLogic.findMounted()?.values?.currentTeam

    // Sync the logic below with the plugin server `getPersonDetails`
    const personDisplayNameProperties = team?.person_display_name_properties ?? PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
    const customPropertyKey = personDisplayNameProperties.find((x: string) => person.properties?.[x])
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

    // Force return of the UUID truncated to 22 characters (unless maxLength is specified)
    // 0199ed4a-5c03-0000-3220-df21df612e95 => 0199ed4a-5c…21df612e95
    // Which keeps the the timestamp at the beginning of the UUID and a unique identifier at the end.
    if (truncateIdUUID && display && isUUIDLike(display)) {
        return midEllipsis(display, maxLength || 22)
    }

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
