import { getAppContext } from 'lib/utils/getAppContext'

import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { getAccessControlDisabledReason } from './accessControlUtils'

jest.mock('lib/utils/getAppContext', () => ({
    getAppContext: jest.fn(),
}))

const mockedGetAppContext = getAppContext as jest.MockedFunction<typeof getAppContext>

describe('getAccessControlDisabledReason', () => {
    afterEach(() => {
        mockedGetAppContext.mockReset()
    })

    // Self-hosted / anonymous instances can bootstrap without `resource_access_control` on the app context
    // (it's only populated for logged-in users, and older backends omit newer resource keys entirely).
    // The export/copy toolbar in the SQL editor reads this on every render, so a missing entry must degrade
    // to a denial reason, never a thrown TypeError that takes down the render.
    test.each([
        ['app context is entirely absent', undefined],
        ['app context has no resource_access_control', {} as AppContext],
        ['resource_access_control has no entry for the resource', { resource_access_control: {} } as AppContext],
        ['the resource entry is null', { resource_access_control: { export: null } } as unknown as AppContext],
    ])('returns a denial reason without throwing when %s', (_label, appContext) => {
        mockedGetAppContext.mockReturnValue(appContext)

        let reason: string | null = null
        expect(() => {
            reason = getAccessControlDisabledReason(AccessControlResourceType.Export, AccessControlLevel.Editor)
        }).not.toThrow()
        expect(reason).toEqual(expect.any(String))
    })

    it('returns null when the app context grants sufficient access', () => {
        mockedGetAppContext.mockReturnValue({
            resource_access_control: { [AccessControlResourceType.Export]: AccessControlLevel.Manager },
        } as unknown as AppContext)

        expect(getAccessControlDisabledReason(AccessControlResourceType.Export, AccessControlLevel.Editor)).toBeNull()
    })
})
