import { AccessControlResourceType } from '~/types'

import { isResourceRolledOut, RESOURCE_ROLLOUT_FLAG_REQUIREMENTS } from './resourcesAccessControlLogic'

describe('resourcesAccessControlLogic', () => {
    describe('isResourceRolledOut', () => {
        it('is always rolled out for resources with no rollout flag requirement', () => {
            expect(isResourceRolledOut(AccessControlResourceType.Dashboard, {})).toBe(true)
        })

        it.each(Object.entries(RESOURCE_ROLLOUT_FLAG_REQUIREMENTS))(
            'hides %s until its rollout flag is enabled',
            (resource, flag) => {
                expect(isResourceRolledOut(resource as AccessControlResourceType, {})).toBe(false)
                expect(isResourceRolledOut(resource as AccessControlResourceType, { [flag]: false })).toBe(false)
                expect(isResourceRolledOut(resource as AccessControlResourceType, { [flag]: true })).toBe(true)
            }
        )
    })
})
