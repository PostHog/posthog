import React from 'react'
import { PersonProperty } from '~/types'

export type GetPersonPropertiesResponse = PersonProperty[]
export type GetPersonPropertiesRequest = undefined

type usePersonProperiesReturnType = { properties: GetPersonPropertiesResponse | undefined; error: boolean }

export const usePersonProperies = (): usePersonProperiesReturnType => {
    const [response, setResponse] = React.useState<usePersonProperiesReturnType>({
        properties: undefined,
        error: false,
    })

    React.useEffect(() => {
        const ac = new AbortController()
        setResponse({ properties: undefined, error: false })
        fetch('/api/person/properties', { signal: ac.signal })
            .then((httpResponse) => httpResponse.json())
            .then((jsonResponse) => setResponse({ properties: jsonResponse, error: false }))
            .catch(() => setResponse({ properties: undefined, error: true }))

        return () => ac.abort()
    }, [])

    return response
}
