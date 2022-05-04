import { AvailableFeature } from '~/types'

let features: AvailableFeature[] = []
export const useAvailableFeatures = (f: AvailableFeature[]): void => {
    features = f
}
export const getAvailableFeatures = (): AvailableFeature[] => {
    return features
}
