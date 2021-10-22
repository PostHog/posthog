import { useValues } from 'kea'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { PersonProperty } from '~/types'

export type GetPersonPropertiesResponse = PersonProperty[]
export type GetPersonPropertiesRequest = undefined

type usePersonProperiesReturnType = { properties: GetPersonPropertiesResponse | undefined; error: boolean }

export const usePersonProperties = (): usePersonProperiesReturnType => {
    const { personProperties } = useValues(personPropertiesModel)
    return { properties: personProperties, error: false }
}
