import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { globalModalsLogic } from '~/layout/globalModalsLogic'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, BillingFeatureType, OrganizationType } from '~/types'

import { newAccountMenuLogic } from './newAccountMenuLogic'

function organizationWithProjects(projectLimit: number | null): OrganizationType {
    const availableProductFeatures: BillingFeatureType[] =
        projectLimit === null
            ? []
            : [{ key: AvailableFeature.ORGANIZATIONS_PROJECTS, name: 'Projects', limit: projectLimit }]
    return { ...MOCK_DEFAULT_ORGANIZATION, available_product_features: availableProductFeatures }
}

describe('newAccountMenuLogic', () => {
    let logic: ReturnType<typeof newAccountMenuLogic.build>

    function setUp(organization: OrganizationType): void {
        initKeaTests(true, undefined, undefined, organization)
        logic = newAccountMenuLogic()
        logic.mount()
        globalModalsLogic.mount()
        upgradeModalLogic.mount()
    }

    test.each([
        {
            name: 'create project at the project limit shows the upgrade modal',
            organization: organizationWithProjects(1),
            create: () => logic.actions.createProject(),
            upgradeModalFeatureKey: AvailableFeature.ORGANIZATIONS_PROJECTS,
            isCreateProjectModalShown: false,
            isCreateOrganizationModalShown: false,
        },
        {
            name: 'create project under the project limit shows the create project modal',
            organization: organizationWithProjects(6),
            create: () => logic.actions.createProject(),
            upgradeModalFeatureKey: null,
            isCreateProjectModalShown: true,
            isCreateOrganizationModalShown: false,
        },
        {
            name: 'create organization without the feature shows the upgrade modal',
            organization: organizationWithProjects(null),
            create: () => logic.actions.createOrganization(),
            upgradeModalFeatureKey: AvailableFeature.ORGANIZATIONS_PROJECTS,
            isCreateProjectModalShown: false,
            isCreateOrganizationModalShown: false,
        },
    ])(
        '$name and closes the menu',
        async ({
            organization,
            create,
            upgradeModalFeatureKey,
            isCreateProjectModalShown,
            isCreateOrganizationModalShown,
        }) => {
            setUp(organization)
            await expectLogic(preflightLogic).toFinishAllListeners()
            logic.actions.setAccountMenuOpen(true)

            create()

            expect(logic.values.isAccountMenuOpen).toBe(false)
            expect(upgradeModalLogic.values.upgradeModalFeatureKey).toBe(upgradeModalFeatureKey)
            expect(globalModalsLogic.values).toMatchObject({
                isCreateProjectModalShown,
                isCreateOrganizationModalShown,
            })
        }
    )
})
