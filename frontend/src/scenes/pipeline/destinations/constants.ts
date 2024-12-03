import { HogFunctionTypeType } from '~/types'

export const getDestinationTypes = (featureFlagEnabled: boolean): HogFunctionTypeType[] =>
    featureFlagEnabled ? ['destination', 'site_destination'] : ['destination']
