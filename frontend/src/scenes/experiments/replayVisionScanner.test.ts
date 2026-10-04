import { type ExperimentExposureCriteria, NodeKind } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'
import {
    experimentScannerPrompt,
    prefillScannerForExperiment,
} from 'products/replay_vision/frontend/replay_scanners/experimentTargeting'
import type { ReplayScanner } from 'products/replay_vision/frontend/replay_scanners/types'

import { experimentScannerBody } from './replayVisionScanner'

describe('replayVisionScanner', () => {
    describe('experimentScannerPrompt', () => {
        it.each([
            {
                name: 'uses the hypothesis as the changed-surface grounding',
                description: 'New one-page checkout',
                expected: 'What the experiment changes: New one-page checkout',
            },
            {
                name: 'falls back to the experiment name when the hypothesis is blank',
                description: '',
                expected: 'Its name is "Checkout redesign"',
            },
            {
                name: 'treats a whitespace-only hypothesis as blank',
                description: '   ',
                expected: 'Its name is "Checkout redesign"',
            },
        ])('$name', ({ description, expected }) => {
            const experiment: Experiment = { ...NEW_EXPERIMENT, name: 'Checkout redesign', description }
            expect(experimentScannerPrompt(experiment)).toContain(expected)
        })
    })

    describe('experimentScannerBody', () => {
        // The experiment is a draft at this point, so a scanner saved on, or without
        // start_on_launch, is refused by the API or never starts.
        it.each([
            {
                name: 'a default exposure event',
                exposure_criteria: undefined,
                expectedFilterTestAccounts: false,
            },
            {
                name: 'a custom exposure event',
                exposure_criteria: {
                    exposure_config: {
                        kind: NodeKind.ExperimentEventExposureConfig,
                        event: 'backend_assigned',
                        properties: [],
                    },
                } satisfies ExperimentExposureCriteria as ExperimentExposureCriteria,
                expectedFilterTestAccounts: false,
            },
            {
                name: 'an experiment that filters test accounts',
                exposure_criteria: { filterTestAccounts: true } satisfies ExperimentExposureCriteria,
                expectedFilterTestAccounts: true,
            },
        ])(
            'saves an experiment scanner that waits for launch, with no filters: $name',
            ({ exposure_criteria, expectedFilterTestAccounts }) => {
                const experiment: Experiment = {
                    ...NEW_EXPERIMENT,
                    id: 123,
                    name: 'Checkout redesign',
                    exposure_criteria,
                }

                const body = experimentScannerBody(experiment, true)

                expect(body).toMatchObject({
                    scanner_type: 'experiment',
                    scanner_config: { experiment_id: 123, variants: null, start_on_launch: true },
                    enabled: false,
                })
                expect(body.experiment_targeting).toBeUndefined()
                expect(body.query).toEqual({
                    kind: NodeKind.RecordingsQuery,
                    filter_test_accounts: expectedFilterTestAccounts,
                })
            }
        )

        // Both entry points feed the same server-derived exposure filter, so the population they
        // build must stay identical.
        it('builds the same population as the scanner wizard prefill', () => {
            const experiment: Experiment = { ...NEW_EXPERIMENT, id: 123, name: 'Checkout redesign' }
            const prefilled = prefillScannerForExperiment(
                { name: 'Frustration score' } as ReplayScanner,
                { experiment, variantKey: null },
                true
            )

            const body = experimentScannerBody(experiment, true)

            expect(prefilled.scanner_type).toEqual(body.scanner_type)
            expect(prefilled.scanner_config).toMatchObject({ experiment_id: 123, variants: null })
            expect(body.query).toEqual(prefilled.query)
        })

        // Until the flag is on for a team, the checkbox keeps creating what it always has.
        it('without the experiment type, saves an off classifier with legacy targeting', () => {
            const experiment: Experiment = { ...NEW_EXPERIMENT, id: 123, name: 'Checkout redesign' }

            const body = experimentScannerBody(experiment, false)

            expect(body).toMatchObject({
                scanner_type: 'classifier',
                experiment_targeting: { experiment_id: 123, variant: null },
                enabled: false,
            })
        })
    })
})
