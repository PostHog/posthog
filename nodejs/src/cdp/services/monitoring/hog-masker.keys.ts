/**
 * Split out from hog-masker.service so operational tooling can address the masker's keys
 * without pulling the service's runtime graph (hogvm, redis pools) in behind it.
 */
export const BASE_REDIS_KEY = process.env.NODE_ENV == 'test' ? '@posthog-test/hog-masker' : '@posthog/hog-masker'

export const MASK_KEY_PREFIX = `${BASE_REDIS_KEY}/mask/`
