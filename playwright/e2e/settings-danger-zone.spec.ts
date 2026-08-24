import { expect, test } from '../utils/workspace-test-base'

test.describe('Project danger zone', () => {
    test('deleting a project requires typed confirmation and actually deletes it', async ({
        page,
        playwrightSetup,
    }) => {
        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        await playwrightSetup.loginAndNavigateToTeam(page, workspace)

        let projectName = ''

        await test.step('open the danger zone and the delete modal', async () => {
            await page.goto('/settings/project-danger-zone')
            const deleteButton = page.locator('[data-attr=delete-project-button]')
            await expect(deleteButton).toBeVisible()
            projectName = ((await deleteButton.innerText()) ?? '').replace(/^Delete\s+/, '').trim()
            await deleteButton.click()
            await expect(page.getByText('Delete the project and its data?')).toBeVisible()
        })

        await test.step('confirm stays disabled until the exact project name is typed', async () => {
            const modal = page.locator('.LemonModal').filter({ hasText: 'Delete the project and its data?' })
            const confirmButton = page.locator('[data-attr=delete-project-ok]')
            await expect(confirmButton).toBeDisabled()
            await modal.getByRole('textbox').fill('wrong-name')
            await expect(confirmButton).toBeDisabled()
            await modal.getByRole('textbox').fill(projectName)
            await expect(confirmButton).toBeEnabled()
        })

        await test.step('confirming marks the project for deletion and locks it out', async () => {
            await page.locator('[data-attr=delete-project-ok]').click()
            // Deletion is async: the API marks is_pending_deletion and the app
            // hard-navigates to the lockout screen.
            await page.waitForURL(/\/project-pending-deletion/, { timeout: 20_000 })
            const resp = await page.request.get(`/api/projects/${workspace.team_id}/`)
            expect((await resp.json()).is_pending_deletion).toBe(true)
        })
    })
})
