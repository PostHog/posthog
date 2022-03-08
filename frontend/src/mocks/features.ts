import { AvailableFeature } from '~/types'

let features: AvailableFeature[] = []
export const useFeatures = (f: AvailableFeature[]): void => {
    features = f
}
export const getFeatures = (): AvailableFeature[] => {
    return features
}
