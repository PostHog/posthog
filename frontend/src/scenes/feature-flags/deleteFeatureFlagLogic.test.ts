import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { deleteFeatureFlagLogic } from './deleteFeatureFlagLogic'

describe('deleteFeatureFlagLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    describe('modal visibility', () => {
        it('shows modal with correct initial values', async () => {
            const logic = deleteFeatureFlagLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.showDeleteFeatureFlagModal(123, 'my-flag', true)
            }).toMatchValues({
                deleteFeatureFlagModalVisible: true,
                deleteFeatureFlag: {
                    featureFlagId: 123,
                    featureFlagKey: 'my-flag',
                    hasUsageDashboard: true,
                    deleteUsageDashboard: false,
                },
            })
        })

        it('hides modal and resets form', async () => {
            const logic = deleteFeatureFlagLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.showDeleteFeatureFlagModal(123, 'my-flag', true)
            }).toMatchValues({
                deleteFeatureFlagModalVisible: true,
            })

            await expectLogic(logic, () => {
                logic.actions.hideDeleteFeatureFlagModal()
            }).toMatchValues({
                deleteFeatureFlagModalVisible: false,
                deleteFeatureFlag: {
                    featureFlagId: null,
                    featureFlagKey: '',
                    hasUsageDashboard: false,
                    deleteUsageDashboard: false,
                },
            })
        })
    })

    describe('dashboard checkbox', () => {
        it('sets hasUsageDashboard to false when flag has no dashboard', async () => {
            const logic = deleteFeatureFlagLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.showDeleteFeatureFlagModal(456, 'no-dashboard-flag', false)
            }).toMatchValues({
                deleteFeatureFlag: expect.objectContaining({
                    featureFlagId: 456,
                    featureFlagKey: 'no-dashboard-flag',
                    hasUsageDashboard: false,
                }),
            })
        })

        it('sets hasUsageDashboard to true when flag has dashboard', async () => {
            const logic = deleteFeatureFlagLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.showDeleteFeatureFlagModal(789, 'with-dashboard-flag', true)
            }).toMatchValues({
                deleteFeatureFlag: expect.objectContaining({
                    featureFlagId: 789,
                    featureFlagKey: 'with-dashboard-flag',
                    hasUsageDashboard: true,
                }),
            })
        })

        it('initializes deleteUsageDashboard to false', async () => {
            const logic = deleteFeatureFlagLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.showDeleteFeatureFlagModal(123, 'test-flag', true)
            }).toMatchValues({
                deleteFeatureFlag: expect.objectContaining({
                    deleteUsageDashboard: false,
                }),
            })
        })
    })
})
