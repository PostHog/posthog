import { PostHogEE } from './types'

/*
 * PostHog EE licensed frontend code is not always included - e.g. in the FOSS version of PostHog.
 *
 * This function is used to dynamically import the EE frontend code, and return an object with the
 * EE licensed functions or an object with `enabled: false` if the EE frontend code is not available.
 */
export const importPostHogEE = async (): Promise<PostHogEE> => {
    // eslint-disable-next-line import/no-restricted-paths
    return await import('../../../ee/frontend/exports')
        .then((eeModuleExports) => eeModuleExports.default)
        .catch(() => {
            return {
                enabled: false,
            }
        })
}
