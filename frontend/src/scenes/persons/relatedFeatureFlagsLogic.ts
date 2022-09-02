import { kea } from "kea";
import { loaders } from "kea-loaders";

export interface RelatedFeatureFlagType {

}

export const relatedFeatureFlagsLogic = kea<relatedFeatureFlagsLogic>([
    loaders({ values }) => ({
        relatedFeatureFlags: [
            null as RelatedFeatureFlagType | null
        ]
    })
])