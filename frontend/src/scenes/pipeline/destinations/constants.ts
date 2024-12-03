import { HogFunctionTypeType } from '~/types'

export const DESTINATION_TYPES = ['destination', 'site_destination'] satisfies HogFunctionTypeType[]
export const SITE_APP_TYPES = ['site_app'] satisfies HogFunctionTypeType[]

// We always pass both types to the function as props (to have a stable key), but filter internally
export const getDestinationTypes = (featureFlagEnabled: boolean): HogFunctionTypeType[] =>
    featureFlagEnabled ? ['destination', 'site_destination'] : ['destination']
