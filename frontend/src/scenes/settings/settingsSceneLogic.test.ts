import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { settingsSceneLogic } from './settingsSceneLogic'

// Mock the survey preview functions
jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderFeedbackWidgetPreview: jest.fn(),
    renderSurveysPreview: jest.fn(),
}))

describe('settingsSceneLogic', () => {
    let logic: ReturnType<typeof settingsSceneLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = settingsSceneLogic()
        logic.mount()
    })

    it('reads filters from the URL', async () => {
        router.actions.push('/settings/project-product-analytics', {}, { 'person-display-name': true })

        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
        })

        expect(router.values.hashParams).toEqual({ 'person-display-name': true })
    })

    it('redirects environment URLs to project', async () => {
        router.actions.push('/settings/environment-autocapture')
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-autocapture',
        })

        router.actions.push('/settings/project-autocapture')
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-autocapture',
        })

        // Test that details sections work correctly
        router.actions.push('/settings/project-details')
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-details',
        })

        // Test that danger zone sections work correctly
        router.actions.push('/settings/project-danger-zone')
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-danger-zone',
        })
    })

    it('redirects level-only URLs to first section', async () => {
        router.actions.push('/settings/environment')
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
        })
        // Should redirect to first section (project-details)
        expect(router.values.location.pathname).toContain('/settings/project-details')

        router.actions.push('/settings/project')
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
        })
        expect(router.values.location.pathname).toContain('/settings/project-details')

        router.actions.push('/settings/organization')
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'organization',
        })
        expect(router.values.location.pathname).toContain('/settings/organization-details')

        router.actions.push('/settings/user')
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'user',
        })
        expect(router.values.location.pathname).toContain('/settings/user-profile')
    })
})
