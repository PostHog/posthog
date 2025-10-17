import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'
import { processEvent } from './index'

interface SemanticVersionTestCase {
    versionString: string
    expected: any
}

const createEvent = (event: Partial<PluginEvent>): PluginEvent =>
    ({
        distinct_id: '1',
        event: '$pageview',
        properties: {
            ...event.properties,
        },
        ...event,
    }) as unknown as PluginEvent

const meta = {
    config: {
        properties: 'targetted_version, another_targetted_version',
    },
    logger: {
        log: jest.fn(),
    },
} as unknown as LegacyTransformationPluginMeta

describe('the semver flattener plugin', () => {
    test('processEvent adds properties when they match config', () => {
        // Create a random event
        const event0: PluginEvent = createEvent({
            uuid: 'the-uuid',
            event: 'booking completed',
            properties: {
                targetted_version: '1.12.20',
                not_a_targetted_version: '1.34.53',
                another_targetted_version: '1.23.14-pre+build.12345',
            },
        }) as PluginEvent

        const processedEvent = processEvent(event0, meta)

        expect(processedEvent?.properties).toEqual({
            targetted_version: '1.12.20',
            targetted_version__major: 1,
            targetted_version__minor: 12,
            targetted_version__patch: 20,
            not_a_targetted_version: '1.34.53',
            another_targetted_version: '1.23.14-pre+build.12345',
            another_targetted_version__major: 1,
            another_targetted_version__minor: 23,
            another_targetted_version__patch: 14,
            another_targetted_version__preRelease: 'pre',
            another_targetted_version__build: 'build.12345',
        })
    })

    const versionExamples: SemanticVersionTestCase[] = [
        {
            versionString: '1.2.3',
            expected: { major: 1, minor: 2, patch: 3, build: undefined },
        },
        {
            versionString: '22.7',
            expected: { major: 22, minor: 7, preRelease: undefined, build: undefined },
        },
        {
            versionString: '22.7-pre-release',
            expected: { major: 22, minor: 7, patch: undefined, preRelease: 'pre-release', build: undefined },
        },
        {
            versionString: '1.0.0-alpha+001',
            expected: { major: 1, minor: 0, patch: 0, preRelease: 'alpha', build: '001' },
        },
        {
            versionString: '1.0.0+20130313144700',
            expected: { major: 1, minor: 0, patch: 0, build: '20130313144700' },
        },
        {
            versionString: '1.2.3-beta+exp.sha.5114f85',
            expected: { major: 1, minor: 2, patch: 3, preRelease: 'beta', build: 'exp.sha.5114f85' },
        },
        {
            versionString: '1.0.0+21AF26D3—-117B344092BD',
            expected: { major: 1, minor: 0, patch: 0, preRelease: undefined, build: '21AF26D3—-117B344092BD' },
        },
    ]
    versionExamples.forEach(({ versionString, expected }) => {
        test(`can process ${versionString}`, () => {
            const event = createEvent({
                properties: {
                    targetted_version: versionString,
                },
            })

            const processedEvent = processEvent(event, meta)

            expect(processedEvent?.properties).toEqual({
                targetted_version: versionString,
                targetted_version__major: expected.major,
                targetted_version__minor: expected.minor,
                targetted_version__patch: expected.patch,
                targetted_version__preRelease: expected.preRelease,
                targetted_version__build: expected.build,
            })
        })
    })
})
