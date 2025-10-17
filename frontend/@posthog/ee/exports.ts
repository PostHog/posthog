import { PostHogEE } from './types'

export default async (): Promise<PostHogEE> => {
    try {
        // this has to import it...
        // oxlint-disable-next-line import/no-restricted-paths
        return (await import('../../../ee/frontend/exports')).default()
    } catch {
        return {
            enabled: false,
        }
    }
}
