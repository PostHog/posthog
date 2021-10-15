import { kea } from 'kea'
import { PersonType } from '~/types'
import { PersonHeaderProps } from 'scenes/persons/PersonHeader'

import { personHeaderLogicType } from './personHeaderLogicType'
import { urls } from 'scenes/urls'

//adapted from https://stackoverflow.com/a/7616484
const hashCode = (str: string): string => {
    let hash = 0

    for (let i = 0; i < str.length; i++) {
        const chr = str.charCodeAt(i)
        hash = (hash << 5) - hash + chr
    }
    return (hash >>> 0).toString()
}

export const personHeaderLogic = kea<personHeaderLogicType>({
    props: {} as PersonHeaderProps,
    key: (props) => (props.person ? hashCode(JSON.stringify(props)) : 'unidentified'),
    reducers: ({ props }) => ({
        withIcon: [props.withIcon || false],
        personLink: [(props.person?.distinct_ids?.length ? urls.person(props.person.distinct_ids[0]) : '') as string],
        isIdentified: [props?.person?.is_identified || false],
    }),
    selectors: {
        personDisplay: [
            () => [(_, props) => props.person],
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
