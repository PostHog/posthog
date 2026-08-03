export const BASE_REDIS_KEY = process.env.NODE_ENV === 'test' ? '@posthog-test/hog-masker' : '@posthog/hog-masker'
export const HOG_MASKER_KEY_PATTERN = `${BASE_REDIS_KEY}/mask/*`
