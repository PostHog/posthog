import { ApiError } from 'lib/api-error'

import { loadOrEmptyOnAccessDenied } from './humanReviewsLoaders'

describe('loadOrEmptyOnAccessDenied', () => {
    const empty = { results: [], count: 0 }

    it('returns the loaded value on success', async () => {
        const loaded = { results: ['a'], count: 1 }
        await expect(loadOrEmptyOnAccessDenied(async () => loaded, empty)).resolves.toBe(loaded)
    })

    it('falls back to empty on a permission_denied 403 instead of throwing', async () => {
        const accessDenied = new ApiError('nope', 403, undefined, { code: 'permission_denied' })
        await expect(
            loadOrEmptyOnAccessDenied(async () => {
                throw accessDenied
            }, empty)
        ).resolves.toBe(empty)
    })

    it('rethrows a 403 that is not an access-denied error', async () => {
        // A 403 without the permission_denied code (e.g. read-only mode) is a real
        // failure the caller must still see, so it must not be swallowed.
        const otherForbidden = new ApiError('read only', 403, undefined, { code: 'read_only_blocked' })
        await expect(
            loadOrEmptyOnAccessDenied(async () => {
                throw otherForbidden
            }, empty)
        ).rejects.toBe(otherForbidden)
    })

    it('rethrows non-permission errors', async () => {
        const serverError = new ApiError('boom', 500)
        await expect(
            loadOrEmptyOnAccessDenied(async () => {
                throw serverError
            }, empty)
        ).rejects.toBe(serverError)
    })
})
