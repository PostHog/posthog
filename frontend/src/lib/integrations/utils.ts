import { capitalizeFirstLetter } from 'lib/utils'

export const getIntegrationNameFromKind = (kind: string): string => {
    return kind == 'google-pubsub'
        ? 'Google Cloud Pub/Sub'
        : kind == 'google-cloud-storage'
        ? 'Google Cloud Storage'
        : kind == 'google-ads'
        ? 'Google Ads'
        : kind == 'linkedin-ads'
        ? 'LinkedIn Ads'
        : kind == 'email'
        ? 'email'
        : kind == 'github'
        ? 'GitHub'
        : capitalizeFirstLetter(kind)
}
