import { ISOTimestamp, ProcessedEvent, ProjectId } from '~/types'

import { applyExperimentExposure } from './apply-experiment-exposure'
import {
    EXPERIMENT_EXPOSURES_PROPERTY,
    EXPERIMENT_EXPOSURE_EVENT,
    ExperimentExposureService,
    buildExperimentExposuresProperty,
    classifyFlagCalledEvent,
    createExperimentExposureService,
    parseExperimentExposureConfig,
} from './experiment-exposure-service'

function processedEvent(overrides: Partial<ProcessedEvent> = {}): ProcessedEvent {
    return {
        uuid: '017a8f4b-0000-4000-8000-000000000001',
        event: '$feature_flag_called',
        properties: {},
        timestamp: '2026-07-30T00:00:00.000Z' as ISOTimestamp,
        team_id: 2,
        project_id: 2 as unknown as ProjectId,
        distinct_id: 'user-1',
        elements_chain: '',
        created_at: null,
        captured_at: null,
        person_id: '017a8f4b-0000-4000-8000-0000000000ff',
        person_properties: {},
        person_created_at: null,
        person_mode: 'full',
        ...overrides,
    }
}

function service(mode: string, teams = '*', excluded = ''): ExperimentExposureService {
    const built = createExperimentExposureService({
        INGESTION_EXPERIMENT_EXPOSURE_MODE: mode,
        INGESTION_EXPERIMENT_EXPOSURE_TEAMS: teams,
        INGESTION_EXPERIMENT_EXPOSURE_EXCLUDED_TEAMS: excluded,
    })
    if (!built) {
        throw new Error(`expected a service for mode ${mode}`)
    }
    return built
}

describe('experiment exposure', () => {
    describe('classifyFlagCalledEvent', () => {
        // The savings case depends entirely on boolean flags being excluded: they are
        // the majority of flag-called volume, so misclassifying them would duplicate
        // most of the traffic instead of a slice of it.
        it.each([
            { label: 'boolean true response', response: true, expected: 'not_experiment' },
            { label: 'boolean false response', response: false, expected: 'not_experiment' },
            { label: 'stringified true response', response: 'true', expected: 'not_experiment' },
            { label: 'stringified false response', response: 'false', expected: 'not_experiment' },
            { label: 'empty response', response: '', expected: 'not_experiment' },
            { label: 'missing response', response: undefined, expected: 'not_experiment' },
            { label: 'variant response', response: 'control', expected: 'experiment' },
            { label: 'other variant response', response: 'test-b', expected: 'experiment' },
        ])('treats $label as $expected', ({ response, expected }) => {
            const result = classifyFlagCalledEvent({
                $feature_flag: 'my-flag',
                $feature_flag_response: response,
            })

            expect(result.kind).toBe(expected)
        })

        it('classifies a boolean response as an exposure when the flag is known to back an experiment', () => {
            const result = classifyFlagCalledEvent({
                $feature_flag: 'bool-flag',
                $feature_flag_response: true,
                $feature_flag_has_experiment: true,
            })

            expect(result).toMatchObject({
                kind: 'experiment',
                signal: 'has_experiment_property',
                flagKey: 'bool-flag',
                variant: 'true',
            })
        })

        it.each([
            { label: 'missing flag key', properties: {} },
            { label: 'non-string flag key', properties: { $feature_flag: 42 } },
            { label: 'empty flag key', properties: { $feature_flag: '' } },
        ])('reports $label as unclassifiable', ({ properties }) => {
            expect(classifyFlagCalledEvent({ ...properties, $feature_flag_response: 'control' }).kind).toBe(
                'unclassifiable'
            )
        })
    })

    describe('buildExperimentExposuresProperty', () => {
        it('keeps only variant-valued flags and strips the property prefix', () => {
            const exposures = buildExperimentExposuresProperty({
                '$feature/multivariate-flag': 'control',
                '$feature/another-flag': 'test',
                // Boolean flags cannot host an experiment, and they are the bulk of
                // these properties by volume. Including them would make the map as
                // large as what it replaces.
                '$feature/boolean-flag': true,
                '$feature/off-flag': false,
                $current_url: 'https://example.com',
            })

            expect(exposures).toEqual({ 'multivariate-flag': 'control', 'another-flag': 'test' })
        })

        it('returns null when no flag could back an experiment', () => {
            expect(buildExperimentExposuresProperty({ '$feature/boolean-flag': true })).toBeNull()
        })
    })

    describe('applyExperimentExposure', () => {
        it('emits nothing and leaves the event untouched in metrics mode', () => {
            const event = processedEvent({
                properties: { $feature_flag: 'f', $feature_flag_response: 'control', '$feature/f': 'control' },
            })

            const exposure = applyExperimentExposure(event, service('metrics'))

            expect(exposure).toBeNull()
            expect(event.event).toBe('$feature_flag_called')
            expect(event.properties).not.toHaveProperty(EXPERIMENT_EXPOSURES_PROPERTY)
        })

        it('emits a duplicate exposure event carrying the resolved variant when enabled', () => {
            const event = processedEvent({
                properties: { $feature_flag: 'f', $feature_flag_response: 'test', '$feature/f': 'test' },
            })

            const exposure = applyExperimentExposure(event, service('enabled'))

            expect(exposure).toMatchObject({
                event: EXPERIMENT_EXPOSURE_EVENT,
                distinct_id: event.distinct_id,
                team_id: event.team_id,
            })
            expect(exposure!.properties).toMatchObject({
                $experiment_variant: 'test',
                $feature_flag: 'f',
                [EXPERIMENT_EXPOSURES_PROPERTY]: { f: 'test' },
            })
        })

        // Kafka delivers at least once, so a replayed batch re-derives the exposure.
        // A non-deterministic uuid would write a second row for the same exposure on
        // every redelivery.
        it('derives a stable exposure uuid from the source event uuid', () => {
            const properties = { $feature_flag: 'f', $feature_flag_response: 'control' }
            const first = applyExperimentExposure(processedEvent({ properties: { ...properties } }), service('enabled'))
            const second = applyExperimentExposure(
                processedEvent({ properties: { ...properties } }),
                service('enabled')
            )

            expect(first!.uuid).toBe(second!.uuid)
            expect(first!.uuid).not.toBe(processedEvent().uuid)
        })

        it('adds the exposures map to non-flag events without emitting a duplicate', () => {
            const event = processedEvent({ event: '$pageview', properties: { '$feature/f': 'control' } })

            const exposure = applyExperimentExposure(event, service('enabled'))

            expect(exposure).toBeNull()
            expect(event.properties[EXPERIMENT_EXPOSURES_PROPERTY]).toEqual({ f: 'control' })
        })

        it('does not write for a team outside the allowlist', () => {
            const event = processedEvent({
                event: '$pageview',
                team_id: 99,
                properties: { '$feature/f': 'control' },
            })

            applyExperimentExposure(event, service('enabled', '2'))

            expect(event.properties).not.toHaveProperty(EXPERIMENT_EXPOSURES_PROPERTY)
        })
    })

    describe('parseExperimentExposureConfig', () => {
        it.each([
            {
                label: 'unknown mode falls back to disabled',
                mode: 'nonsense',
                teams: '',
                excluded: '',
                expected: 'disabled',
            },
            { label: 'valid mode is kept', mode: 'enabled', teams: '*', excluded: '', expected: 'enabled' },
            // The escape hatch has to stop writes, but not the accounting it was never
            // meant to disable.
            {
                label: 'excluding every team downgrades writes to metrics',
                mode: 'enabled',
                teams: '*',
                excluded: '*',
                expected: 'metrics',
            },
        ])('$label', ({ mode, teams, excluded, expected }) => {
            expect(parseExperimentExposureConfig(mode, teams, excluded).mode).toBe(expected)
        })
    })
})
