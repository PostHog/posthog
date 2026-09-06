import { type ExperimentExposureCriteria, NodeKind } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'

import { experimentScannerBody, experimentScannerPrompt } from './replayVisionScanner'

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
        // Every experiment shape must produce the same population, because the API resolves the
        // exposed sessions from the targeting. A query that carries an exposure filter is the old
        // client-built shape, and the API rejects it.
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
            'targets all variants of the experiment and keeps the query free of filters: $name',
            ({ exposure_criteria, expectedFilterTestAccounts }) => {
                const experiment: Experiment = {
                    ...NEW_EXPERIMENT,
                    id: 123,
                    name: 'Checkout redesign',
                    exposure_criteria,
                }

                const body = experimentScannerBody(experiment)

                expect(body.experiment_targeting).toEqual({ experiment_id: 123, variant: null })
                expect(body.query).toEqual({
                    kind: NodeKind.RecordingsQuery,
                    filter_test_accounts: expectedFilterTestAccounts,
                })
            }
        )
    })
})
