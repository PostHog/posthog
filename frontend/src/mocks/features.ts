import { AvailableFeature, BillingV2FeatureType } from '~/types'

let features: AvailableFeature[] = []
export const useAvailableFeatures = (f: AvailableFeature[]): void => {
    features = f
}
export const getAvailableProductFeatures = (): BillingV2FeatureType[] => {
    return features.map((feature) => {
        return {
            key: feature,
            name: feature,
        }
    })
}
