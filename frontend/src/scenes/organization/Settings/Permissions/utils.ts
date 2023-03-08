import { Resource } from '~/types'

export function getSingularType(type: Resource): string {
    switch (type) {
        case Resource.FEATURE_FLAGS:
            return 'flag'
        default:
            return 'resource'
    }
}
