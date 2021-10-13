import { kea } from 'kea'
import { PersonType } from '~/types'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { uuid } from 'lib/utils'

import { personHeaderLogicType } from './personHeaderLogicType'
import { urls } from 'scenes/urls'
const toKey = (props: PersonHeader): string => (props.person ? JSON.stringify(props) : uuid())

const toUrl = (person: Partial<PersonType> | null | undefined): string | undefined =>
    person?.distinct_ids?.length ? urls.person(person.distinct_ids[0]) : ''

export const personHeaderLogic = kea<personHeaderLogicType>({
    props: {} as PersonHeader,
    reducers: ({ props }) => ({
        withIcon: [props.withIcon || false],
        person: [(props.person || null) as Partial<PersonType>],
        key: [toKey(props)],
        personLink: [toUrl(props.person) as string],
        isIdentified: [props?.person?.is_identified || false],
    }),
    selectors: {
        personDisplay: [
            (selectors) => [selectors.person],
            (person: Partial<PersonType>) => {
                let display, displayId
                const propertyIdentifier = person?.properties
                    ? person.properties.email || person.properties.name || person.properties.username
                    : 'with no ids'
                const customIdentifier =
                    typeof propertyIdentifier === 'object' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

                if (!person?.distinct_ids?.length) {
                    displayId = null
                } else {
                    const baseId = person.distinct_ids[0].replace(/\W/g, '')
                    displayId = baseId.substr(baseId.length - 5).toUpperCase()
                }

                if (person?.is_identified) {
                    display = customIdentifier ? customIdentifier : `Identified user ${displayId}`
                } else {
                    display = `Unidentified ${customIdentifier || `user ${displayId}`}`
                }

                return display
            },
        ],
    },
})
