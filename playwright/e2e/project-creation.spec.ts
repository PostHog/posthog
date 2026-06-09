import { randomString } from '../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

// Creating a new project on an existing org is a fundamental flow that spans the modal, the
// projects API (gated by the organizations_projects feature), and the post-create team switch.
// Only a full-stack browser test proves all three agree, so it lives here rather than a unit test.
test.describe('Project creation', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            organization_name: randomString('Project Creation Org'),
            no_demo_data: true,
            skip_onboarding: true,
            // Required to create a second project — without it both the UI and API block it.
            available_features: ['organizations_projects'],
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('creates a new project within the existing organization', async ({ page }) => {
        const originalProjectName = workspace!.team_name
        const newProjectName = randomString('New Project')

        await test.step('open the create-project modal from the account menu', async () => {
            await page.getByTestId('new-account-menu-button').click()
            await page.getByTestId('new-account-menu-create-project-icon-button').click()

            const modal = page.getByRole('dialog')
            await expect(modal).toBeVisible()
            await expect(modal).toContainText(`Create a project within ${workspace!.organization_name}`)
        })

        await test.step('name and create the project', async () => {
            const modal = page.getByRole('dialog')
            await modal.getByRole('textbox').fill(newProjectName)
            await modal.getByRole('button', { name: 'Create project' }).click()
        })

        await test.step('app switches into the newly created project', async () => {
            // On success the app navigates into the new project, so its name becomes the active one.
            await expect(page.getByTestId('new-account-menu-button')).toContainText(newProjectName, { timeout: 30000 })
        })

        await test.step('both projects are listed under the same organization', async () => {
            await page.getByTestId('new-account-menu-button').click()
            await page.getByTestId('new-account-menu-all-projects-button').click()

            await expect(page.getByLabel('Search projects')).toBeVisible()
            await expect(page.getByRole('option', { name: originalProjectName })).toBeVisible()
            await expect(page.getByRole('option', { name: newProjectName })).toBeVisible()
        })
    })
})
