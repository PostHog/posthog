import React from 'react'
import { PersonProperty } from '~/types'

export type GetPersonPropertiesResponse = PersonProperty[]
export type GetPersonPropertiesRequest = undefined

export const usePersonProperies = (): GetPersonPropertiesResponse | undefined => {
    const [properties, setProperties] = React.useState<GetPersonPropertiesResponse | undefined>(undefined)

    React.useEffect(() => {
        const ac = new AbortController()
        fetch('/api/person/properties', { signal: ac.signal })
            .then((httpResponse) => httpResponse.json())
            .then((jsonResponse) => setProperties(jsonResponse))

        return () => ac.abort()
    }, [])

    return properties
}
