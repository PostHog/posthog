import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import * as restrictedArea from 'lib/components/RestrictedArea'

import { useMoveProjectDisabledReasons } from './ProjectMove'

describe('useMoveProjectDisabledReasons', () => {
    beforeEach(() => {
        jest.spyOn(restrictedArea, 'useRestrictedArea').mockReturnValue(null)
    })
    afterEach(() => {
        jest.clearAllMocks()
    })

    it('returns early when user is restricted', () => {
        jest.spyOn(restrictedArea, 'useRestrictedArea').mockReturnValue('not allowed')

        const { disabledReason, restrictedReason } = useMoveProjectDisabledReasons({
            otherOrganizations: [],
            targetOrganization: null,
        })

        expect(disabledReason).toEqual('not allowed')
        expect(restrictedReason).toEqual('not allowed')
    })

    it('returns restricted reason when user is not part of any other organizations', () => {
        const { disabledReason, restrictedReason } = useMoveProjectDisabledReasons({
            otherOrganizations: [],
            targetOrganization: null,
        })

        expect(disabledReason).toEqual('You must be a member of another organization')
        expect(restrictedReason).toEqual('You must be a member of another organization')
    })

    it('returns disabled reason when user has not selected target organization', () => {
        const { disabledReason, restrictedReason } = useMoveProjectDisabledReasons({
            otherOrganizations: [MOCK_DEFAULT_ORGANIZATION],
            targetOrganization: null,
        })

        expect(disabledReason).toEqual('Please select the target organization')
        expect(restrictedReason).toBeNull()
    })

    it('returns no disabled reasons when valid', () => {
        const { disabledReason, restrictedReason } = useMoveProjectDisabledReasons({
            otherOrganizations: [MOCK_DEFAULT_ORGANIZATION],
            targetOrganization: MOCK_DEFAULT_ORGANIZATION,
        })

        expect(disabledReason).toBeNull()
        expect(restrictedReason).toBeNull()
    })
})
