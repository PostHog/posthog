import { PostHogEE } from './types'

export default async (): Promise<PostHogEE> => {
    // eslint-disable-next-line import/no-restricted-paths
    return import('../../../ee/frontend/exports')
        .then((ee) => {
            return ee.default()
        })
        .catch(() => {
            return {
                enabled: false,
            }
        })
}
