import { PersonsPage } from '../../page-models/personsPage'
import { personWithMultipleIds, personsWithIdentity } from '../../utils/test-data'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Persons', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    function personsApi(distinctId: string): string {
        return `/api/environments/${workspace!.team_id}/persons/?distinct_id=${distinctId}`
    }

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            skip_onboarding: true,
            no_demo_data: true,
            persons: [personWithMultipleIds.person],
            events: [...personsWithIdentity.events, ...personWithMultipleIds.events],
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('View persons list, navigate to detail, and browse tabs', async ({ page }) => {
        const persons = new PersonsPage(page)
        const { emailUser } = personsWithIdentity.expected

        await test.step('search for the email user and navigate to their detail page', async () => {
            // goToList now waits for data to load before proceeding
            await persons.goToList()
            await persons.searchFor(emailUser)
            await persons.clickFirstPerson()
            await expect(page).toHaveURL(/\/person/)
        })

        await test.step('verify display name is resolved from person properties, not a UUID', async () => {
            await expect(page.getByRole('heading', { name: 'Alice' })).toBeVisible()
        })

        await test.step('verify the primary distinct ID is shown in the caption', async () => {
            await expect(persons.personDistinctId).toContainText(emailUser)
        })

        await test.step('verify properties tab shows seeded person properties', async () => {
            await persons.goToPropertiesTab()
            const propsTable = persons.detailTable()
            const nameValue = await propsTable.row('name').column('value')
            expect(nameValue).toContain('Alice')
            const planValue = await propsTable.row('plan').column('value')
            expect(planValue).toContain('pro')
        })

        await test.step('verify events tab shows the seeded pageview events', async () => {
            await persons.goToEventsTab()
            await expect(page.getByText('Showing all')).toBeVisible()
            const eventsTable = persons.detailTable()
            const eventNames = await eventsTable.column('event')
            expect(eventNames).toHaveLength(2)
            expect(eventNames.every((name) => name.includes('Pageview'))).toBe(true)
        })

        await test.step('switch to cohorts tab and verify empty state', async () => {
            await persons.cohortsTab.click()
            await expect(page.getByText("This person doesn't belong to any cohort")).toBeVisible()
        })
    })

    test('Split a person with multiple distinct IDs', async ({ page }) => {
        const persons = new PersonsPage(page)
        const { primaryDistinctId } = personWithMultipleIds.expected
        const secondaryDistinctId = personWithMultipleIds.person.distinct_ids[1]

        await test.step('search for the multi-ID person and navigate to their detail page', async () => {
            await persons.goToList()
            await persons.searchFor(primaryDistinctId)
            await persons.clickFirstPerson()
        })

        await test.step('open the split modal and verify it describes the split', async () => {
            await persons.openSplitIdsModal()
            const modal = page.getByRole('dialog')
            await expect(modal.getByText('This will create')).toBeVisible()
        })

        await test.step('execute the split and verify redirect to persons list', async () => {
            const splitResponse = page.waitForResponse(
                (resp) => resp.url().includes('/split/') && resp.status() === 201
            )
            await page.getByRole('dialog').getByRole('button', { name: 'Split persons' }).click()
            await splitResponse
            await expect(page.getByText(/succesfully split/i)).toBeVisible()
            await expect(page).toHaveURL(/\/persons/)
        })

        await test.step('wait for async split to complete then verify both persons exist', async () => {
            // Split is a long running task — we tell the user that it may take a couple of minutes to see results
            await expect
                .poll(
                    async () => {
                        const [primaryResp, secondaryResp] = await Promise.all([
                            page.request.get(personsApi(primaryDistinctId)),
                            page.request.get(personsApi(secondaryDistinctId)),
                        ])
                        const primaryData = await primaryResp.json()
                        const secondaryData = await secondaryResp.json()
                        return {
                            primaryIds: primaryData.results[0]?.distinct_ids,
                            secondaryIds: secondaryData.results[0]?.distinct_ids,
                        }
                    },
                    { timeout: 60_000, intervals: [1_000, 2_000, 5_000] }
                )
                .toEqual({
                    primaryIds: [primaryDistinctId],
                    secondaryIds: [secondaryDistinctId],
                })

            await page.goto(`/person/${encodeURIComponent(primaryDistinctId)}`)
            await expect(persons.tabs).toBeVisible()
            await expect(persons.personDistinctId).toContainText(primaryDistinctId)
            await expect(persons.splitIdsButton).not.toBeVisible()
        })
    })

    test('Can delete a person', async ({ page }) => {
        const persons = new PersonsPage(page)

        await test.step('navigate to a person detail page', async () => {
            await persons.goToList()
            await persons.clickNthPerson(0)
        })

        await test.step('open the delete confirmation modal', async () => {
            await persons.openDeleteModal()
        })

        await test.step('verify the confirmation text input is visible', async () => {
            await expect(page.getByText(/to confirm, please type/i)).toBeVisible()
            await expect(page.getByPlaceholder('delete')).toBeVisible()
        })

        await test.step('cancel the modal and verify it closes', async () => {
            await persons.cancelDeleteModal()
        })

        await test.step('verify the person page is still visible', async () => {
            await expect(persons.tabs).toBeVisible()
        })
    })
})
