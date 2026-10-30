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

interface BooleanRunSpec {
    result: boolean | null
    skipped?: boolean
}

// Identical runs on both evaluations, so any difference in how they render comes from the declared polarity.
const BOOLEAN_RUNS: BooleanRunSpec[] = [
    { result: true },
    { result: true },
    { result: true },
    { result: true },
    { result: false },
    { result: null },
    { result: false, skipped: true },
]

const SCREENSHOT_DIR = path.join(__dirname, '../../../../.playwright-screenshots')

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

        await test.step('the polarity choice round-trips through save + reload', async () => {
            // Created through the API, not seeded: a save needs at least one condition set, which a seed lacks.
            const createResponse = await page.request.post(`/api/projects/${workspace.team_id}/evaluations/`, {
                headers: { Authorization: `Bearer ${workspace.personal_api_key}` },
                data: {
                    name: 'User struggled',
                    evaluation_type: 'hog',
                    evaluation_config: { source: HOG_SOURCE },
                    output_type: 'boolean',
                    output_config: {},
                    conditions: [{ id: 'all', rollout_percentage: 100, properties: [] }],
                },
            })
            expect(createResponse.ok()).toBe(true)
            const evaluationId = ((await createResponse.json()) as { id: string }).id

            const passOption = page.getByTestId('llma-evaluation-true-is-pass')
            const failOption = page.getByTestId('llma-evaluation-true-is-failure')
            const gotoConfiguration = async (): Promise<void> => {
                await page.goto(`/ai-evals/evaluations/${evaluationId}`)
                await page.getByTestId('llma-evaluation-configuration-tab').click()
                await page.getByTestId('llma-evaluation-create-step-check').click()
            }

            for (const option of [failOption, passOption]) {
                await gotoConfiguration()
                await option.click()
                await Promise.all([
                    page.waitForResponse(
                        (resp) => resp.url().includes('/evaluations/') && resp.request().method() === 'PATCH'
                    ),
                    page.getByTestId('llma-evaluation-save-bottom').click(),
                ])

                // A full page load, so the choice comes back from the API rather than form state.
                await gotoConfiguration()
                await expect(option).toHaveClass(/LemonButton--primary/)
            }
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
            await page.getByTestId('llma-evaluation-create-step-check').click()
            await expect(page.getByTestId('llma-evaluation-true-is-pass')).toHaveClass(/LemonButton--primary/)
        })
    })

    test('seeded results propagate correctly across the runs table and edge cases', async ({
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
            enabled: true,
        })
        const evalAId = detector.evaluation_id

        const quality = await playwrightSetup.seedEvaluation({
            team_id: workspace.team_id,
            name: 'Response is accurate',
            evaluation_type: 'hog',
            evaluation_config: { source: HOG_SOURCE },
            output_type: 'boolean',
            output_config: {},
            enabled: true,
        })
        const evalBId = quality.evaluation_id

        await playwrightSetup.seedEvents(workspace.team_id, [
            ...buildBooleanRunEvents(evalAId, 'User struggled', BOOLEAN_RUNS, Date.now()),
            ...buildBooleanRunEvents(evalBId, 'Response is accurate', BOOLEAN_RUNS, Date.now()),
        ])

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

        await test.step('N/A and a skipped run behave the same way for the non-detector evaluation', async () => {
            await expect(page.getByText('N/A', { exact: true })).toHaveCount(1)

            await page.goto(`/ai-evals/evaluations/${evalBId}`)
            await expect(page.getByRole('heading', { name: 'Response is accurate' })).toBeVisible()
            const naTag = page.getByText('N/A', { exact: true })
            const skippedTag = page.getByText('Skipped', { exact: true })
            await expect(naTag).toHaveCount(1)
            await expect(naTag).toHaveClass(/LemonTag--muted/)
            await expect(skippedTag).toHaveCount(1)
            await expect(skippedTag).toHaveClass(/LemonTag--muted/)

            // Mirrors the detector's Passing/Failing check above — a skipped run is excluded
            // from both buckets regardless of which polarity the evaluation declares.
            await page.getByRole('button', { name: 'Passing', exact: true }).click()
            await expect(skippedTag).toHaveCount(0)
            await page.getByRole('button', { name: 'Failing', exact: true }).click()
            await expect(skippedTag).toHaveCount(0)
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
            await page.getByTestId('llma-evaluation-create-step-check').click()
            await expect(page.getByTestId('llma-evaluation-true-is-failure')).toHaveCount(0)

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
