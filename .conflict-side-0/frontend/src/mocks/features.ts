import { AvailableFeature, BillingFeatureType } from '~/types'

let features: AvailableFeature[] = []
export const useAvailableFeatures = (f: AvailableFeature[]): void => {
    features = f
}
export const getAvailableProductFeatures = (): BillingFeatureType[] => {
    return features.map((feature) => {
        return {
            key: feature,
            name: feature,
        }
    })
}
