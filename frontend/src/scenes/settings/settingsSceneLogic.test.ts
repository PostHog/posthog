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

    it('opens the AI observability BYOK settings deep link', async () => {
        router.actions.push('/settings/project-ai-observability', {}, { 'ai-observability-byok': true })

        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-ai-observability',
        })

        expect(router.values.hashParams).toEqual({ 'ai-observability-byok': true })
    })

    it('redirects legacy AI observability BYOK settings deep links', async () => {
        router.actions.push('/settings/project-llm-analytics', {}, { 'llm-analytics-byok': true })

        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-ai-observability',
        })

        expect(router.values.location.pathname).toContain('/settings/project-ai-observability')
        expect(router.values.location.hash).toBe('#ai-observability-byok')
        expect(router.values.hashParams).toHaveProperty('ai-observability-byok')
        expect(router.values.hashParams).not.toHaveProperty('llm-analytics-byok')

        router.actions.push('/settings/environment-llm-analytics', {}, { 'llm-analytics-byok': true })

        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-ai-observability',
        })

        expect(router.values.location.pathname).toContain('/settings/project-ai-observability')
        expect(router.values.location.hash).toBe('#ai-observability-byok')
        expect(router.values.hashParams).toHaveProperty('ai-observability-byok')
        expect(router.values.hashParams).not.toHaveProperty('llm-analytics-byok')
    })

    it('redirects internal-user-filtering deep links to its new section', async () => {
        // The setting moved from the product analytics section to Customization; links in docs,
        // CDP filter warnings, and bookmarks still point at the old section.
        router.actions.push('/settings/project-product-analytics', {}, { 'internal-user-filtering': true })

        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-customization',
        })

        expect(router.values.location.pathname).toContain('/settings/project-customization')
        expect(router.values.hashParams).toHaveProperty('internal-user-filtering')

        // Level-only URLs (as emitted by CDP filter warnings) redirect too.
        router.actions.push('/settings/project', {}, { 'internal-user-filtering': true })

        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-customization',
        })

        expect(router.values.location.pathname).toContain('/settings/project-customization')
        expect(router.values.hashParams).toHaveProperty('internal-user-filtering')
    })

    it('redirects the removed toolbar section to web analytics', async () => {
        router.actions.push('/settings/project-toolbar')

        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-web-analytics',
        })
        expect(router.values.location.pathname).toContain('/settings/project-web-analytics')

        router.actions.push('/settings/environment-toolbar')

        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-web-analytics',
        })
        expect(router.values.location.pathname).toContain('/settings/project-web-analytics')
    })

    it('rewrites the legacy toolbar authorized-urls deep link to the web analytics setting', async () => {
        router.actions.push('/settings/project-toolbar', {}, { 'authorized-urls': null })

        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-web-analytics',
        })
        expect(router.values.location.pathname).toContain('/settings/project-web-analytics')
        expect(router.values.location.hash).toBe('#web-analytics-authorized-urls')
        expect(router.values.hashParams).toHaveProperty('web-analytics-authorized-urls')
        expect(router.values.hashParams).not.toHaveProperty('authorized-urls')
    })

    it('redirects level-only URLs to first section', async () => {
        // Each push switches to a different level, so no section at the target level is
        // selected yet and the redirect to the first section runs.
        router.actions.push('/settings/environment')
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
        })
        // Should redirect to first section (project-details)
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

        // The redirect keeps hash params, so `/settings/project#variables`-style links
        // still scroll to their setting.
        router.actions.push('/settings/project', {}, { variables: true })
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
        })
        expect(router.values.location.pathname).toContain('/settings/project-details')
        expect(router.values.hashParams).toHaveProperty('variables')
    })

    it('redirects the project-members guess to organization members', async () => {
        // Members are organization-level, so `/settings/project-members` is the intuitive wrong
        // guess, and it used to dead-end on "Setting not found".
        router.actions.push('/settings/project-members', {}, { members: true })

        await expectLogic(logic).toMatchValues({
            selectedLevel: 'organization',
            selectedSectionId: 'organization-members',
        })
        expect(router.values.location.pathname).toContain('/settings/organization-members')
        // The redirect keeps hash params, so deep links to a specific setting still scroll to it.
        expect(router.values.hashParams).toHaveProperty('members')
    })

    it('leaves an unmapped section id on the not-found path', async () => {
        // Aliases are added one at a time on purpose. A catch-all redirect for anything unrecognized
        // would shadow the app-level redirects in scenes.ts and would drop the `not_found_shown`
        // report that makes broken settings links visible in the first place.
        router.actions.push('/settings/organization-teapot')

        await expectLogic(logic).toMatchValues({
            selectedSectionId: 'organization-teapot',
            selectedSection: null,
        })
        expect(router.values.location.pathname).toContain('/settings/organization-teapot')
    })

    it('does not bounce a level-only URL when already on a section at that level', async () => {
        router.actions.push('/settings/project-autocapture')
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-autocapture',
        })

        // Clicking the "Settings" nav link routes to the bare level URL; while already viewing a
        // project settings page it must be a no-op, not a redirect back to the first section.
        router.actions.push('/settings/project')
        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
            selectedSectionId: 'project-autocapture',
        })
        expect(router.values.location.pathname).toMatch(/\/settings\/project$/)
    })
})

describe('settingsSceneLogic on a cold page load', () => {
    // The tests above navigate after mounting, which only covers clicks inside the app. A URL that
    // arrives from outside (pasted, opened in a new tab, followed from an old bookmark) is already
    // set before the logic mounts, and that is the path a broken settings link actually takes.
    it('applies a section alias when the URL is set before the logic mounts', async () => {
        initKeaTests()
        router.actions.push('/settings/project-members')

        const logic = settingsSceneLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            selectedSectionId: 'organization-members',
        })
        expect(router.values.location.pathname).toContain('/settings/organization-members')
    })
})
