import { AccessControlResourceType } from '~/types'

import { isResourceRolledOut, RESOURCE_ROLLOUT_FLAG_REQUIREMENTS } from './resourcesAccessControlLogic'

describe('resourcesAccessControlLogic', () => {
    describe('isResourceRolledOut', () => {
        it('uses the customer tasks rollout flag for the customer task resource', () => {
            expect(RESOURCE_ROLLOUT_FLAG_REQUIREMENTS[AccessControlResourceType.CustomerTask]).toBe(
                'customer-analytics-customer-tasks'
            )
            expect(isResourceRolledOut(AccessControlResourceType.CustomerTask, {})).toBe(false)
            expect(
                isResourceRolledOut(AccessControlResourceType.CustomerTask, {
                    'customer-analytics-customer-tasks': true,
                })
            ).toBe(true)
        })

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
