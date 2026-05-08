/**
 * Regression: experiment metric event validation must not reject:
 *   1. Empty-string event names — pydantic permits `event: ""` but it's not a queryable
 *      event name. Treat it like None / "All events" instead of raising the misleading
 *      `Event(s) '' not found` error customers were hitting.
 *   2. Events scoped to the project (not just the specific team) — the EventDefinition
 *      list endpoint is project-scoped, so users can pick events ingested by sibling
 *      teams in the same project. Validation must mirror that scope or it rejects
 *      legitimate selections.
 */
import { expect, test } from '../../utils/workspace-test-base'

const FLAG_KEY = 'e2e-metric-validation-flag'

// No events need to be seeded: empty/whitespace event names should never reach the
// EventDefinition lookup at all (the extractor must skip them, just like None).
// Their presence in the payload alone exercises the regression path.

type ValidationCase = {
    label: string
    flagSuffix: string
    experimentName: string
    metric: Record<string, unknown>
}

const cases: ValidationCase[] = [
    {
        label: 'event=""',
        flagSuffix: '',
        experimentName: 'Empty event regression',
        metric: {
            kind: 'ExperimentMetric',
            metric_type: 'mean',
            goal: 'increase',
            source: { kind: 'EventsNode', event: '' },
        },
    },
    {
        label: 'whitespace-only event',
        flagSuffix: '-whitespace',
        experimentName: 'Whitespace event regression',
        metric: {
            kind: 'ExperimentMetric',
            metric_type: 'ratio',
            goal: 'increase',
            numerator: { kind: 'EventsNode', event: '   ' },
            denominator: { kind: 'EventsNode', event: '' },
        },
    },
]

test.describe('experiment metric validation', () => {
    for (const tc of cases) {
        test(`PATCH with ${tc.label} does not raise misleading "Event(s) ... not found"`, async ({
            page,
            playwrightSetup,
        }) => {
            const workspace = await playwrightSetup.createWorkspace({
                skip_onboarding: true,
                no_demo_data: true,
            })

            const apiHeaders = {
                Authorization: `Bearer ${workspace.personal_api_key}`,
                'Content-Type': 'application/json',
            }

            // Create a draft experiment with no metrics
            const createResp = await page.request.post(`/api/projects/${workspace.team_id}/experiments/`, {
                headers: apiHeaders,
                data: {
                    name: tc.experimentName,
                    feature_flag_key: `${FLAG_KEY}${tc.flagSuffix}`,
                    parameters: {
                        feature_flag_variants: [
                            { key: 'control', name: 'Control', rollout_percentage: 50 },
                            { key: 'test', name: 'Test', rollout_percentage: 50 },
                        ],
                    },
                    metrics: [],
                },
            })
            expect(createResp.ok()).toBe(true)
            const experiment = await createResp.json()

            // PATCH with a metric whose EventsNode carries an empty/whitespace event
            // should not raise a 400 with "Event(s) ... not found". The empty string
            // is not a valid event name, but it also shouldn't be treated as a failed
            // lookup against EventDefinition — it should be skipped, just like None.
            const patchResp = await page.request.patch(
                `/api/projects/${workspace.team_id}/experiments/${experiment.id}/`,
                {
                    headers: apiHeaders,
                    data: { metrics: [tc.metric] },
                }
            )

            const patchBody = await patchResp.text()
            expect(patchResp.status(), patchBody).toBe(200)
            expect(patchBody).not.toContain('not found')
        })
    }
})
