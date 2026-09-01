import { expect, test } from '@playwright-utils/workspace-test-base'
import fs from 'fs'
import path from 'path'

// Reused verbatim from llmEvaluationLogic.ts's LEGACY_HOG_DEFAULT_SOURCES — a known-good Hog
// snippet, so seeding an evaluation directly still stores compilable bytecode.
const HOG_SOURCE = `// Check that the output is not empty
let result := length(output) > 0
if (not result) {
    print('Output is empty')
}
return result`

const SCREENSHOT_DIR = path.join(__dirname, '../../../../.playwright-screenshots')

test.describe('AI observability boolean evaluation polarity', () => {
    test.beforeAll(() => {
        fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })
    })

    test.use({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' })

    test('the polarity switch round-trips, and a legacy config behaves as pass-on-true', async ({
        page,
        playwrightSetup,
    }) => {
        test.setTimeout(120_000)

        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        await playwrightSetup.login(page, workspace)

        await test.step('the switch renders under Allow N/A responses and round-trips through save + reload', async () => {
            await page.goto('/ai-evals/evaluations/new')
            await expect(page.getByRole('heading', { name: 'New evaluation' })).toBeVisible()

            await page.getByPlaceholder('e.g., Helpfulness Check').fill('User struggled')
            await page.getByRole('button', { name: 'LLM as a judge' }).click()
            await page.getByRole('menuitem', { name: 'Hog code' }).click()

            const trueIsFailureSwitch = page.getByTestId('llma-evaluation-true-is-failure-switch')
            const allowsNaLabel = page.getByText('Allow N/A responses', { exact: true })
            const trueIsFailureLabel = page.getByText('A true result flags a problem', { exact: true })

            // Settle scrolling before taking any measurement — every bounding box read below has
            // to share one coordinate space with the eventual screenshot clip, and a later click
            // auto-scrolling the page would otherwise invalidate boxes read before it.
            await trueIsFailureSwitch.scrollIntoViewIfNeeded()

            await expect(allowsNaLabel).toBeVisible()
            await expect(trueIsFailureLabel).toBeVisible()
            const naBox = await allowsNaLabel.boundingBox()
            const flagBox = await trueIsFailureLabel.boundingBox()
            if (!naBox || !flagBox) {
                throw new Error('Expected both switch labels to have a bounding box')
            }
            expect(flagBox.y).toBeGreaterThan(naBox.y)

            await expect(trueIsFailureSwitch).toHaveAttribute('aria-checked', 'false')
            await expect(page.getByText('A true result counts as a pass', { exact: true })).toBeVisible()

            await trueIsFailureSwitch.click()
            await expect(trueIsFailureSwitch).toHaveAttribute('aria-checked', 'true')
            const failDescription = page.getByText('A true result counts as a fail', { exact: true })
            await expect(failDescription).toBeVisible()

            const naDescription = page.getByText('Evaluation must return true or false', { exact: true })
            const failBox = await failDescription.boundingBox()
            const switchBox = await trueIsFailureSwitch.boundingBox()
            const naDescriptionBox = await naDescription.boundingBox()
            if (failBox && switchBox && naDescriptionBox) {
                const pad = 24
                const left = Math.min(naBox.x, switchBox.x) - pad
                const top = naBox.y - 10
                const right =
                    Math.max(
                        naBox.x + naBox.width,
                        naDescriptionBox.x + naDescriptionBox.width,
                        failBox.x + failBox.width
                    ) + pad
                const bottom = failBox.y + failBox.height + pad
                await page.screenshot({
                    path: path.join(SCREENSHOT_DIR, '01-switch.png'),
                    clip: { x: left, y: top, width: right - left, height: bottom - top },
                    animations: 'disabled',
                })
            }

            const [createResponse] = await Promise.all([
                page.waitForResponse(
                    (resp) => resp.url().includes('/evaluations/') && resp.request().method() === 'POST'
                ),
                page.getByRole('button', { name: 'Create evaluation' }).click(),
            ])
            await expect(page).toHaveURL(/\/ai-evals\/evaluations$/, { timeout: 30_000 })
            const created = await createResponse.json()
            const evalAId = created.id as string

            const gotoEvalA = async (): Promise<void> => {
                await page.goto(`/ai-evals/evaluations/${evalAId}`)
                await page.getByTestId('llma-evaluation-configuration-tab').click()
            }

            await gotoEvalA()
            await expect(page.getByTestId('llma-evaluation-true-is-failure-switch')).toHaveAttribute(
                'aria-checked',
                'true'
            )
            await page.reload()
            await page.getByTestId('llma-evaluation-configuration-tab').click()
            await expect(page.getByTestId('llma-evaluation-true-is-failure-switch')).toHaveAttribute(
                'aria-checked',
                'true'
            )

            await page.getByTestId('llma-evaluation-true-is-failure-switch').click()
            await expect(page.getByTestId('llma-evaluation-true-is-failure-switch')).toHaveAttribute(
                'aria-checked',
                'false'
            )
            await page.getByRole('button', { name: 'Save changes' }).click()
            await expect(page).toHaveURL(/\/ai-evals\/evaluations$/, { timeout: 30_000 })

            await gotoEvalA()
            await expect(page.getByTestId('llma-evaluation-true-is-failure-switch')).toHaveAttribute(
                'aria-checked',
                'false'
            )
            await page.reload()
            await page.getByTestId('llma-evaluation-configuration-tab').click()
            await expect(page.getByTestId('llma-evaluation-true-is-failure-switch')).toHaveAttribute(
                'aria-checked',
                'false'
            )
        })

        await test.step('a legacy evaluation whose config never had the key behaves as pass-on-true', async () => {
            const legacy = await playwrightSetup.seedEvaluation({
                team_id: workspace.team_id,
                name: 'Response is accurate',
                evaluation_type: 'hog',
                evaluation_config: { source: HOG_SOURCE },
                output_type: 'boolean',
                output_config: {},
            })

            await page.goto(`/ai-evals/evaluations/${legacy.evaluation_id}`)
            await page.getByTestId('llma-evaluation-configuration-tab').click()
            await expect(page.getByTestId('llma-evaluation-true-is-failure-switch')).toHaveAttribute(
                'aria-checked',
                'false'
            )
            await expect(page.getByText('A true result counts as a pass', { exact: true })).toBeVisible()
        })
    })
})
