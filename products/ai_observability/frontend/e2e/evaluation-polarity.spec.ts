import type { PlaywrightSetupEvent } from '@playwright-utils/playwright-setup'
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

interface BooleanRunSpec {
    result: boolean | null
    skipped?: boolean
}

function buildBooleanRunEvents(
    evaluationId: string,
    evaluationName: string,
    specs: BooleanRunSpec[],
    baseTimestampMs: number
): PlaywrightSetupEvent[] {
    return specs.map((spec, index) => {
        const suffix = `${evaluationId.slice(0, 8)}-${index}`
        const properties: Record<string, unknown> = {
            $ai_evaluation_id: evaluationId,
            $ai_evaluation_name: evaluationName,
            $ai_trace_id: `e2e-trace-${suffix}`,
            $ai_target_event_id: `e2e-gen-${suffix}`,
            $ai_evaluation_reasoning: 'Synthetic e2e reasoning.',
        }
        if (spec.result !== null) {
            properties.$ai_evaluation_result = spec.result
        }
        if (spec.skipped) {
            properties.$ai_evaluation_skipped = true
        }
        return {
            event: '$ai_evaluation',
            distinct_id: `e2e-eval-user-${suffix}`,
            timestamp: new Date(baseTimestampMs + index * 1000).toISOString(),
            properties,
        }
    })
}

function buildSentimentRunEvents(
    evaluationId: string,
    evaluationName: string,
    labels: string[],
    baseTimestampMs: number
): PlaywrightSetupEvent[] {
    return labels.map((label, index) => {
        const suffix = `${evaluationId.slice(0, 8)}-${index}`
        return {
            event: '$ai_evaluation',
            distinct_id: `e2e-eval-user-${suffix}`,
            timestamp: new Date(baseTimestampMs + index * 1000).toISOString(),
            properties: {
                $ai_evaluation_id: evaluationId,
                $ai_evaluation_name: evaluationName,
                $ai_sentiment_label: label,
                $ai_trace_id: `e2e-trace-${suffix}`,
                $ai_target_event_id: `e2e-gen-${suffix}`,
            },
        }
    })
}

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

    test('seeded results propagate correctly across the list, the runs table, and edge cases', async ({
        page,
        playwrightSetup,
    }) => {
        test.setTimeout(180_000)

        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        await playwrightSetup.login(page, workspace)

        const detector = await playwrightSetup.seedEvaluation({
            team_id: workspace.team_id,
            name: 'User struggled',
            evaluation_type: 'hog',
            evaluation_config: { source: HOG_SOURCE },
            output_type: 'boolean',
            output_config: { true_is_failure: true },
        })
        const evalAId = detector.evaluation_id

        const quality = await playwrightSetup.seedEvaluation({
            team_id: workspace.team_id,
            name: 'Response is accurate',
            evaluation_type: 'hog',
            evaluation_config: { source: HOG_SOURCE },
            output_type: 'boolean',
            output_config: {},
        })
        const evalBId = quality.evaluation_id

        await test.step('identical results invert the pass rate between a detector and a quality check', async () => {
            const now = Date.now()
            const detectorEvents = buildBooleanRunEvents(
                evalAId,
                'User struggled',
                [
                    { result: true },
                    { result: true },
                    { result: true },
                    { result: true },
                    { result: false },
                    { result: null },
                    { result: false, skipped: true },
                ],
                now
            )
            const qualityEvents = buildBooleanRunEvents(
                evalBId,
                'Response is accurate',
                [
                    { result: true },
                    { result: true },
                    { result: true },
                    { result: true },
                    { result: false },
                    { result: null },
                ],
                now
            )
            await playwrightSetup.seedEvents(workspace.team_id, [...detectorEvents, ...qualityEvents])

            await page.goto('/ai-evals/evaluations')
            const detectorRow = page.getByRole('row', { name: /User struggled/ })
            const qualityRow = page.getByRole('row', { name: /Response is accurate/ })
            await expect(detectorRow).toBeVisible()
            await expect(qualityRow).toBeVisible()

            // Scroll before measuring — the table can render below the fold on a fresh
            // page load, and a clip built from boxes measured pre-scroll lands off-image.
            await detectorRow.scrollIntoViewIfNeeded()

            const detectorRate = detectorRow.getByText('20%', { exact: true })
            const qualityRate = qualityRow.getByText('80%', { exact: true })
            await expect(detectorRate).toBeVisible()
            await expect(detectorRate).toHaveClass(/text-danger/)
            await expect(qualityRate).toBeVisible()
            await expect(qualityRate).toHaveClass(/text-success/)

            const detectorBox = await detectorRow.boundingBox()
            const qualityBox = await qualityRow.boundingBox()
            if (detectorBox && qualityBox) {
                const pad = 12
                const top = Math.max(0, Math.min(detectorBox.y, qualityBox.y) - pad)
                const bottom = Math.max(detectorBox.y + detectorBox.height, qualityBox.y + qualityBox.height) + pad
                const left = Math.max(0, Math.min(detectorBox.x, qualityBox.x) - pad)
                const width = Math.max(detectorBox.width, qualityBox.width) + pad * 2
                await page.screenshot({
                    path: path.join(SCREENSHOT_DIR, '02-list-pass-rate.png'),
                    clip: { x: left, y: top, width, height: bottom - top },
                    animations: 'disabled',
                })
            }
        })

        await test.step('a true run renders as the undesirable outcome, and the Passing/Failing filter inverts', async () => {
            await page.goto(`/ai-evals/evaluations/${evalAId}`)
            await expect(page.getByRole('heading', { name: 'User struggled' })).toBeVisible()

            const trueTags = page.getByText('True', { exact: true })
            const falseTags = page.getByText('False', { exact: true })
            await expect(trueTags).toHaveCount(4)
            await expect(falseTags).toHaveCount(1)
            for (let i = 0; i < 4; i++) {
                await expect(trueTags.nth(i)).toHaveClass(/LemonTag--danger/)
            }
            await expect(falseTags).toHaveClass(/LemonTag--success/)

            await page.getByRole('button', { name: 'Passing', exact: true }).click()
            await expect(trueTags).toHaveCount(0)
            await expect(falseTags).toHaveCount(1)
            await expect(page.getByText('N/A', { exact: true })).toHaveCount(0)
            await expect(page.getByText('Skipped', { exact: true })).toHaveCount(0)

            await page.getByRole('button', { name: 'Failing', exact: true }).click()
            await expect(trueTags).toHaveCount(4)
            await expect(falseTags).toHaveCount(0)
            await expect(page.getByText('N/A', { exact: true })).toHaveCount(0)
            await expect(page.getByText('Skipped', { exact: true })).toHaveCount(0)

            const runsTable = page.getByRole('table')
            await runsTable.scrollIntoViewIfNeeded()
            const filtersAndTable = await runsTable.boundingBox()
            const failingButton = await page.getByRole('button', { name: 'Failing', exact: true }).boundingBox()
            if (filtersAndTable && failingButton) {
                const pad = 16
                const top = Math.max(0, Math.min(filtersAndTable.y, failingButton.y) - pad)
                const left = Math.max(0, Math.min(filtersAndTable.x, failingButton.x) - pad)
                const right = filtersAndTable.x + filtersAndTable.width + pad
                const bottom = Math.min(filtersAndTable.y + 420, filtersAndTable.y + filtersAndTable.height) + pad
                await page.screenshot({
                    path: path.join(SCREENSHOT_DIR, '03-run-outcomes.png'),
                    clip: { x: left, y: top, width: right - left, height: bottom - top },
                    animations: 'disabled',
                })
            }
        })

        await test.step('a skipped run is excluded from both the passing and failing buckets', async () => {
            await page.getByRole('button', { name: 'All', exact: true }).click()
            const skippedTag = page.getByText('Skipped', { exact: true })
            await expect(skippedTag).toHaveCount(1)
            await expect(skippedTag).toHaveClass(/LemonTag--muted/)
        })

        await test.step('an N/A result stays N/A regardless of the evaluation polarity', async () => {
            await expect(page.getByText('N/A', { exact: true })).toHaveCount(1)

            await page.goto(`/ai-evals/evaluations/${evalBId}`)
            await expect(page.getByRole('heading', { name: 'Response is accurate' })).toBeVisible()
            const naTag = page.getByText('N/A', { exact: true })
            await expect(naTag).toHaveCount(1)
            await expect(naTag).toHaveClass(/LemonTag--muted/)
        })

        await test.step('a sentiment evaluation is entirely unaffected by the flag', async () => {
            const sentiment = await playwrightSetup.seedEvaluation({
                team_id: workspace.team_id,
                name: 'User message tone',
                evaluation_type: 'sentiment',
                evaluation_config: { source: 'user_messages' },
                output_type: 'sentiment',
                output_config: {},
            })
            const evalCId = sentiment.evaluation_id

            await page.goto(`/ai-evals/evaluations/${evalCId}`)
            await page.getByTestId('llma-evaluation-configuration-tab').click()
            await expect(page.getByText('Allow N/A responses', { exact: true })).toHaveCount(0)
            await expect(page.getByText('A true result flags a problem', { exact: true })).toHaveCount(0)

            const sentimentEvents = buildSentimentRunEvents(
                evalCId,
                'User message tone',
                ['negative', 'positive'],
                Date.now()
            )
            await playwrightSetup.seedEvents(workspace.team_id, sentimentEvents)

            await page.goto(`/ai-evals/evaluations/${evalCId}`)
            await expect(page.getByRole('heading', { name: 'User message tone' })).toBeVisible()
            // The config-tab visit above already mounted this page once, loading (and caching)
            // an empty runs query before any events existed — a plain reload replays that cached
            // empty result. Force a fresh query past the cache, same as a user clicking Refresh.
            await page.getByTestId('llma-evaluation-refresh-runs').click()
            // Default filter is 'negative' (DEFAULT_SENTIMENT_RUNS_FILTER) — switch to 'All' so
            // both seeded runs show, and scope tag lookups to the table so they can't resolve to
            // the segmented filter buttons, which carry the same label text ('Negative', 'Positive').
            await page.getByRole('button', { name: 'All', exact: true }).click()
            const runsTable = page.getByRole('table')
            const negativeTag = runsTable.getByText('Negative', { exact: true })
            const positiveTag = runsTable.getByText('Positive', { exact: true })
            await expect(negativeTag).toBeVisible()
            await expect(positiveTag).toBeVisible()
            await expect(negativeTag).toHaveClass(/LemonTag--danger/)
            await expect(positiveTag).toHaveClass(/LemonTag--success/)
        })
    })
})
