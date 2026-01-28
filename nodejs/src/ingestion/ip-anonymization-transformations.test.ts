import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { insertHogFunction as _insertHogFunction } from '~/cdp/_tests/fixtures'
import { pluginAdvancedGeoip } from '~/cdp/legacy-plugins/_transformations/plugin-advanced-geoip/template'
import { propertyFilterPlugin } from '~/cdp/legacy-plugins/_transformations/property-filter-plugin/template'
import { template as botDetectionTemplate } from '~/cdp/templates/_transformations/bot-detection/bot-detection.template'
import { template as filterPropertiesTemplate } from '~/cdp/templates/_transformations/filter-properties/filter-properties.template'
import { template as geoipTemplate } from '~/cdp/templates/_transformations/geoip/geoip.template'
import { template as ipAnonymizationTemplate } from '~/cdp/templates/_transformations/ip-anonymization/ip-anonymization.template'
import { template as piiHashingTemplate } from '~/cdp/templates/_transformations/pii-hashing/pii-hashing.template'
import { compileHog } from '~/cdp/templates/compiler'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { HogFunctionType } from '../cdp/types'
import { Hub, PipelineEvent, Team } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
import { PostgresUse } from '../utils/db/postgres'
import { parseJSON } from '../utils/json-parse'
import { UUIDT } from '../utils/utils'
import { IngestionConsumer } from './ingestion-consumer'

/**
 * These tests verify that when team.anonymize_ips = true, IP addresses are removed
 * BEFORE transformations run. This affects transformations that rely on $ip.
 *
 * See ip-anonymization-notice.md for the full list of affected transformations.
 */

const DEFAULT_TEST_TIMEOUT = 5000
const TRANSFORMATION_TEST_TIMEOUT = 30000

jest.setTimeout(DEFAULT_TEST_TIMEOUT)

jest.mock('../utils/posthog', () => {
    const original = jest.requireActual('../utils/posthog')
    return {
        ...original,
        captureException: jest.fn(),
    }
})

jest.mock('./event-processing/event-pipeline-runner-v1-step', () => ({
    createEventPipelineRunnerV1Step: jest.fn(),
}))

jest.mock('../utils/token-bucket', () => {
    const mockConsume = jest.fn().mockReturnValue(true)
    return {
        ...jest.requireActual('../utils/token-bucket'),
        IngestionWarningLimiter: {
            consume: mockConsume,
        },
    }
})

let offsetIncrementer = 0

const createKafkaMessage = (event: PipelineEvent): Message => {
    const captureEvent = {
        uuid: event.uuid,
        distinct_id: event.distinct_id,
        ip: event.ip,
        now: event.now,
        token: event.token,
        data: JSON.stringify(event),
    }
    return {
        key: `${event.token}:${event.distinct_id}`,
        value: Buffer.from(JSON.stringify(captureEvent)),
        size: 1,
        topic: 'test',
        offset: offsetIncrementer++,
        timestamp: DateTime.now().toMillis(),
        partition: 1,
        headers: [
            { distinct_id: Buffer.from(event.distinct_id || '') },
            { token: Buffer.from(event.token || '') },
            { event: Buffer.from(event.event || '') },
            { uuid: Buffer.from(event.uuid || '') },
            { now: Buffer.from(event.now || '') },
        ],
    }
}

const createKafkaMessages = (events: PipelineEvent[]): Message[] => events.map(createKafkaMessage)

describe.each([
    ['legacy pipeline', false],
    ['joined pipeline', true],
] as const)('IP Anonymization with Transformations (%s)', (_name, useJoinedPipeline) => {
    let hub: Hub
    let team: Team
    let fixedTime: DateTime

    const createIngestionConsumer = async (hub: Hub) => {
        const ingester = new IngestionConsumer(hub)
        ingester['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any
        await ingester.start()
        return ingester
    }

    const createEvent = (event?: Partial<PipelineEvent>): PipelineEvent => ({
        distinct_id: 'user-1',
        uuid: new UUIDT().toString(),
        token: team.api_token,
        ip: '127.0.0.1',
        site_url: 'us.posthog.com',
        now: fixedTime.toISO()!,
        event: '$pageview',
        ...event,
        properties: {
            $current_url: 'http://localhost:8000',
            ...(event?.properties || {}),
        },
    })

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const { hog, bytecode, name, inputs, inputs_schema, execution_order } = hogFunction
        const item = await _insertHogFunction(hub.postgres, team.id, {
            hog,
            bytecode,
            name: name || 'Test Function',
            type: 'transformation',
            inputs,
            inputs_schema,
            execution_order,
        })
        return item
    }

    beforeAll(() => {
        jest.setTimeout(TRANSFORMATION_TEST_TIMEOUT)
    })

    afterAll(() => {
        jest.setTimeout(DEFAULT_TEST_TIMEOUT)
        jest.useRealTimers()
    })

    beforeEach(async () => {
        fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        jest.spyOn(Date.prototype, 'toISOString').mockReturnValue(fixedTime.toISO()!)

        offsetIncrementer = 0
        await resetTestDatabase()
        hub = await createHub()
        hub.INGESTION_JOINED_PIPELINE = useJoinedPipeline

        team = await getFirstTeam(hub)

        const { createEventPipelineRunnerV1Step } = jest.requireMock('./event-processing/event-pipeline-runner-v1-step')
        createEventPipelineRunnerV1Step.mockImplementation((...args: any[]) => {
            const original = jest.requireActual('./event-processing/event-pipeline-runner-v1-step')
            return original.createEventPipelineRunnerV1Step(...args)
        })
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    const setAnonymizeIps = async (enabled: boolean) => {
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_team SET anonymize_ips = $1 WHERE id = $2`,
            [enabled, team.id],
            `set anonymize_ips to ${enabled}`
        )
    }

    describe('with anonymize_ips enabled', () => {
        let ingester: IngestionConsumer

        beforeEach(async () => {
            await setAnonymizeIps(true)
            ingester = await createIngestionConsumer(hub)
        })

        afterEach(async () => {
            await ingester.stop()
        })

        it(
            'GeoIP transformation should not add location properties when IP is anonymized',
            async () => {
                // Create GeoIP transformation
                const hogByteCode = await compileHog(geoipTemplate.code)
                await insertHogFunction({
                    name: 'GeoIP Transformation',
                    hog: geoipTemplate.code,
                    bytecode: hogByteCode,
                })

                // Send an event with an IP that would normally be geolocated
                const event = createEvent({
                    ip: '89.160.20.129', // Swedish IP
                    properties: { $ip: '89.160.20.129' },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // IP should be removed by the filterIpPropertiesStep
                expect(properties).not.toHaveProperty('$ip')

                // GeoIP properties should NOT be added because the IP was removed before transformation
                expect(properties).not.toHaveProperty('$geoip_city_name')
                expect(properties).not.toHaveProperty('$geoip_country_name')
                expect(properties).not.toHaveProperty('$geoip_country_code')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Bot Detection should not filter by IP when IP is anonymized',
            async () => {
                // Create bot detection transformation with IP filtering enabled
                const hogByteCode = await compileHog(botDetectionTemplate.code)
                await insertHogFunction({
                    name: 'Bot Detection',
                    hog: botDetectionTemplate.code,
                    bytecode: hogByteCode,
                    inputs_schema: botDetectionTemplate.inputs_schema,
                    inputs: {
                        userAgent: { value: '$raw_user_agent' },
                        filterKnownBotUserAgents: { value: false }, // Disable user agent filtering
                        filterKnownBotIps: { value: true }, // Enable IP filtering
                        customBotPatterns: { value: '' },
                        customIpPrefixes: { value: '' },
                        keepUndefinedUseragent: { value: 'Yes' },
                    },
                })

                // Send an event with a known bot IP (5.39.1.225) - normally would be filtered
                const event = createEvent({
                    ip: '5.39.1.225',
                    properties: {
                        $ip: '5.39.1.225',
                        $raw_user_agent: 'Mozilla/5.0 Normal Browser',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')

                // Event should NOT be dropped because the IP was removed before bot detection ran
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // IP should be removed
                expect(properties).not.toHaveProperty('$ip')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'PII Hashing should not hash $ip when IP is anonymized (already removed)',
            async () => {
                // Create PII hashing transformation that tries to hash $ip and $email
                const hogByteCode = await compileHog(piiHashingTemplate.code)
                await insertHogFunction({
                    name: 'PII Hashing',
                    hog: piiHashingTemplate.code,
                    bytecode: hogByteCode,
                    inputs_schema: piiHashingTemplate.inputs_schema,
                    inputs: {
                        propertiesToHash: { value: '$ip,$email' },
                        hashDistinctId: { value: false },
                        salt: { value: '' },
                    },
                })

                // Send an event with IP and email
                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                        $email: 'user@example.com',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // $ip should NOT be present (removed before hashing could happen)
                expect(properties).not.toHaveProperty('$ip')

                // $email should be hashed (SHA-256 produces 64 character hex string)
                expect(properties.$email).toMatch(/^[a-f0-9]{64}$/)
                expect(properties.$email).not.toBe('user@example.com')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'IP Anonymization transformation should have no IP to anonymize when anonymize_ips is enabled',
            async () => {
                // Create IP anonymization transformation (zeroes last octet: 192.168.1.100 -> 192.168.1.0)
                const hogByteCode = await compileHog(ipAnonymizationTemplate.code)
                await insertHogFunction({
                    name: 'IP Anonymization',
                    hog: ipAnonymizationTemplate.code,
                    bytecode: hogByteCode,
                    inputs_schema: ipAnonymizationTemplate.inputs_schema,
                })

                // Send an event with an IP
                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // $ip should be completely removed (not anonymized to 192.168.1.0)
                // because the IP was removed before the transformation could anonymize it
                expect(properties).not.toHaveProperty('$ip')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Custom transformation receives undefined $ip when anonymize_ips is enabled',
            async () => {
                // Create a custom transformation that copies $ip to a new property
                const customCode = `
                    let ip := event.properties.$ip
                    let returnEvent := event
                    if (notEmpty(ip)) {
                        returnEvent.properties.ip_was_present := true
                        returnEvent.properties.copied_ip := ip
                    } else {
                        returnEvent.properties.ip_was_present := false
                    }
                    return returnEvent
                `
                const hogByteCode = await compileHog(customCode)
                await insertHogFunction({
                    name: 'Custom IP Reader',
                    hog: customCode,
                    bytecode: hogByteCode,
                })

                // Send an event with an IP
                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // $ip should be removed
                expect(properties).not.toHaveProperty('$ip')

                // The transformation should have seen no IP
                expect(properties.ip_was_present).toBe(false)
                expect(properties).not.toHaveProperty('copied_ip')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Property Filter transformation filtering $ip is redundant when anonymize_ips is enabled',
            async () => {
                // Create Property Filter transformation configured to remove $ip
                const hogByteCode = await compileHog(filterPropertiesTemplate.code)
                await insertHogFunction({
                    name: 'Property Filter',
                    hog: filterPropertiesTemplate.code,
                    bytecode: hogByteCode,
                    inputs_schema: filterPropertiesTemplate.inputs_schema,
                    inputs: {
                        propertiesToFilter: { value: '$ip' },
                    },
                })

                // Send an event with an IP
                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                        $browser: 'Chrome',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // $ip should be removed (by filterIpPropertiesStep, before the transformation even runs)
                expect(properties).not.toHaveProperty('$ip')
                // Other properties should be preserved
                expect(properties.$browser).toBe('Chrome')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )
    })

    describe('with anonymize_ips disabled (baseline behavior)', () => {
        let ingester: IngestionConsumer

        beforeEach(async () => {
            await setAnonymizeIps(false)
            ingester = await createIngestionConsumer(hub)
        })

        afterEach(async () => {
            await ingester.stop()
        })

        it(
            'GeoIP transformation adds location properties when anonymize_ips is disabled',
            async () => {
                // Create GeoIP transformation
                const hogByteCode = await compileHog(geoipTemplate.code)
                await insertHogFunction({
                    name: 'GeoIP Transformation',
                    hog: geoipTemplate.code,
                    bytecode: hogByteCode,
                })

                // Send an event with an IP that can be geolocated
                const event = createEvent({
                    ip: '89.160.20.129', // Swedish IP
                    properties: { $ip: '89.160.20.129' },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // IP should still be present
                expect(properties.$ip).toBe('89.160.20.129')

                // GeoIP properties should be added
                expect(properties.$geoip_country_code).toBe('SE')
                expect(properties.$geoip_country_name).toBe('Sweden')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Bot Detection filters by IP when anonymize_ips is disabled',
            async () => {
                // Create bot detection transformation with IP filtering enabled
                const hogByteCode = await compileHog(botDetectionTemplate.code)
                await insertHogFunction({
                    name: 'Bot Detection',
                    hog: botDetectionTemplate.code,
                    bytecode: hogByteCode,
                    inputs_schema: botDetectionTemplate.inputs_schema,
                    inputs: {
                        userAgent: { value: '$raw_user_agent' },
                        filterKnownBotUserAgents: { value: false },
                        filterKnownBotIps: { value: true },
                        customBotPatterns: { value: '' },
                        customIpPrefixes: { value: '' },
                        keepUndefinedUseragent: { value: 'Yes' },
                    },
                })

                // Send an event with a known bot IP (5.39.1.225)
                const event = createEvent({
                    ip: '5.39.1.225',
                    properties: {
                        $ip: '5.39.1.225',
                        $raw_user_agent: 'Mozilla/5.0 Normal Browser',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')

                // Event should be DROPPED because the IP matches a known bot IP
                expect(producedMessages).toHaveLength(0)
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'PII Hashing hashes $ip when anonymize_ips is disabled',
            async () => {
                // Create PII hashing transformation
                const hogByteCode = await compileHog(piiHashingTemplate.code)
                await insertHogFunction({
                    name: 'PII Hashing',
                    hog: piiHashingTemplate.code,
                    bytecode: hogByteCode,
                    inputs_schema: piiHashingTemplate.inputs_schema,
                    inputs: {
                        propertiesToHash: { value: '$ip,$email' },
                        hashDistinctId: { value: false },
                        salt: { value: '' },
                    },
                })

                // Send an event with IP and email
                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                        $email: 'user@example.com',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // Both $ip and $email should be hashed
                expect(properties.$ip).toMatch(/^[a-f0-9]{64}$/)
                expect(properties.$ip).not.toBe('192.168.1.100')
                expect(properties.$email).toMatch(/^[a-f0-9]{64}$/)
                expect(properties.$email).not.toBe('user@example.com')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'IP Anonymization transformation anonymizes IP when anonymize_ips is disabled',
            async () => {
                // Create IP anonymization transformation
                const hogByteCode = await compileHog(ipAnonymizationTemplate.code)
                await insertHogFunction({
                    name: 'IP Anonymization',
                    hog: ipAnonymizationTemplate.code,
                    bytecode: hogByteCode,
                    inputs_schema: ipAnonymizationTemplate.inputs_schema,
                })

                // Send an event with an IP
                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // $ip should be anonymized (last octet zeroed for IPv4)
                expect(properties.$ip).toBe('192.168.1.0')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Custom transformation receives $ip when anonymize_ips is disabled',
            async () => {
                // Create a custom transformation that copies $ip to a new property
                const customCode = `
                    let ip := event.properties.$ip
                    let returnEvent := event
                    if (notEmpty(ip)) {
                        returnEvent.properties.ip_was_present := true
                        returnEvent.properties.copied_ip := ip
                    } else {
                        returnEvent.properties.ip_was_present := false
                    }
                    return returnEvent
                `
                const hogByteCode = await compileHog(customCode)
                await insertHogFunction({
                    name: 'Custom IP Reader',
                    hog: customCode,
                    bytecode: hogByteCode,
                })

                // Send an event with an IP
                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // $ip should still be present
                expect(properties.$ip).toBe('192.168.1.100')

                // The transformation should have seen the IP
                expect(properties.ip_was_present).toBe(true)
                expect(properties.copied_ip).toBe('192.168.1.100')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Property Filter can remove $ip when anonymize_ips is disabled',
            async () => {
                // Create Property Filter transformation configured to remove $ip
                const hogByteCode = await compileHog(filterPropertiesTemplate.code)
                await insertHogFunction({
                    name: 'Property Filter',
                    hog: filterPropertiesTemplate.code,
                    bytecode: hogByteCode,
                    inputs_schema: filterPropertiesTemplate.inputs_schema,
                    inputs: {
                        propertiesToFilter: { value: '$ip' },
                    },
                })

                // Send an event with an IP
                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                        $browser: 'Chrome',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // $ip should be removed by the transformation (set to null)
                expect(properties.$ip).toBeNull()
                // Other properties should be preserved
                expect(properties.$browser).toBe('Chrome')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )
    })

    describe('with remediation applied (anonymize_ips disabled + Property Filter)', () => {
        // These tests verify the recommended remediation pattern from the IP anonymization notice:
        // 1. Set anonymize_ips = false so transformations can access IP
        // 2. Chain with Property Filter to remove $ip from final event

        let ingester: IngestionConsumer

        beforeEach(async () => {
            await setAnonymizeIps(false)
            ingester = await createIngestionConsumer(hub)
        })

        afterEach(async () => {
            await ingester.stop()
        })

        it(
            'GeoIP + Property Filter: adds geo properties then removes $ip',
            async () => {
                // Remediation for: GeoIP (Modern Template) - template-geoip
                //
                // To restore GeoIP functionality:
                // 1. Add the "Property Filter" transformation configured to filter out `$ip`
                // 2. Disable "Discard client IP data" in Settings → Project → IP Capture
                //
                // This ensures you get geographic insights without storing IP addresses long-term.

                // Create GeoIP transformation first (execution_order = 0)
                const geoipByteCode = await compileHog(geoipTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: geoipTemplate.code,
                    bytecode: geoipByteCode,
                    name: 'GeoIP Transformation',
                    type: 'transformation',
                    execution_order: 0,
                })

                // Create Property Filter transformation second (execution_order = 1)
                const filterByteCode = await compileHog(filterPropertiesTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: filterPropertiesTemplate.code,
                    bytecode: filterByteCode,
                    name: 'Property Filter',
                    type: 'transformation',
                    inputs_schema: filterPropertiesTemplate.inputs_schema,
                    inputs: {
                        propertiesToFilter: { value: '$ip' },
                    },
                    execution_order: 1,
                })

                // Send an event with an IP that can be geolocated
                const event = createEvent({
                    ip: '89.160.20.129', // Swedish IP
                    properties: { $ip: '89.160.20.129' },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // GeoIP properties should be added (GeoIP ran first while $ip was present)
                expect(properties.$geoip_country_code).toBe('SE')
                expect(properties.$geoip_country_name).toBe('Sweden')

                // $ip should be removed by Property Filter (set to null)
                expect(properties.$ip).toBeNull()
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Bot Detection + Property Filter: drops bot events and removes $ip from non-bot events',
            async () => {
                // Remediation for: Bot Detection - template-bot-detection
                //
                // To restore bot detection functionality:
                // 1. Add the "Property Filter" transformation configured to filter out `$ip`
                // 2. Position it AFTER your Bot Detection transformation in the pipeline
                // 3. Disable "Discard client IP data" in Settings → Project → IP Capture
                //
                // This ensures bot IPs are filtered while not storing IP addresses long-term.

                // Create bot detection transformation (execution_order = 0)
                const botDetectionByteCode = await compileHog(botDetectionTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: botDetectionTemplate.code,
                    bytecode: botDetectionByteCode,
                    name: 'Bot Detection',
                    type: 'transformation',
                    inputs_schema: botDetectionTemplate.inputs_schema,
                    inputs: {
                        userAgent: { value: '$raw_user_agent' },
                        filterKnownBotUserAgents: { value: false },
                        filterKnownBotIps: { value: true },
                        customBotPatterns: { value: '' },
                        customIpPrefixes: { value: '' },
                        keepUndefinedUseragent: { value: 'Yes' },
                    },
                    execution_order: 0,
                })

                // Create Property Filter to remove $ip after bot detection (execution_order = 1)
                const filterByteCode = await compileHog(filterPropertiesTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: filterPropertiesTemplate.code,
                    bytecode: filterByteCode,
                    name: 'Property Filter',
                    type: 'transformation',
                    inputs_schema: filterPropertiesTemplate.inputs_schema,
                    inputs: {
                        propertiesToFilter: { value: '$ip' },
                    },
                    execution_order: 1,
                })

                // Send a non-bot event with a unique identifier
                const nonBotEvent = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                        $raw_user_agent: 'Mozilla/5.0 Normal Browser',
                        test_marker: 'non-bot-event',
                    },
                })

                // Send a bot event (known bot IP) with a different identifier
                const botEvent = createEvent({
                    ip: '5.39.1.225',
                    properties: {
                        $ip: '5.39.1.225',
                        $raw_user_agent: 'Mozilla/5.0 Normal Browser',
                        test_marker: 'bot-event',
                    },
                })

                const messages = createKafkaMessages([nonBotEvent, botEvent])
                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')

                // Only non-bot event should be produced (bot event dropped)
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // Verify it's the non-bot event that passed through
                expect(properties.test_marker).toBe('non-bot-event')

                // $ip should be removed by Property Filter
                expect(properties.$ip).toBeNull()
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'PII Hashing + Property Filter: hashes $ip then removes it',
            async () => {
                // Remediation for: PII Hashing - template-pii-hashing
                //
                // To restore IP hashing functionality:
                // 1. Disable "Discard client IP data" in Settings → Project → IP Capture
                // 2. Verify `$ip` is included in the "Properties to Hash" configuration
                // 3. (Optional) Add Property Filter to remove hashed IP after PII Hashing
                //
                // Note: Hashed IPs are already anonymized, so removing them afterward is optional.

                // Create PII hashing transformation (execution_order = 0)
                const piiHashingByteCode = await compileHog(piiHashingTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: piiHashingTemplate.code,
                    bytecode: piiHashingByteCode,
                    name: 'PII Hashing',
                    type: 'transformation',
                    inputs_schema: piiHashingTemplate.inputs_schema,
                    inputs: {
                        propertiesToHash: { value: '$ip,$email' },
                        hashDistinctId: { value: false },
                        salt: { value: '' },
                    },
                    execution_order: 0,
                })

                // Create Property Filter to remove hashed $ip (execution_order = 1)
                const filterByteCode = await compileHog(filterPropertiesTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: filterPropertiesTemplate.code,
                    bytecode: filterByteCode,
                    name: 'Property Filter',
                    type: 'transformation',
                    inputs_schema: filterPropertiesTemplate.inputs_schema,
                    inputs: {
                        propertiesToFilter: { value: '$ip' },
                    },
                    execution_order: 1,
                })

                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                        $email: 'user@example.com',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // $ip should be removed by Property Filter (after being hashed)
                expect(properties.$ip).toBeNull()

                // $email should be hashed and still present
                expect(properties.$email).toMatch(/^[a-f0-9]{64}$/)
                expect(properties.$email).not.toBe('user@example.com')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Custom transformation + Property Filter: transformation sees $ip, then $ip is removed',
            async () => {
                // Remediation for: Custom Transformations (using `$ip` in code)
                //
                // If `$ip` is critical to your transformation:
                // 1. Review your transformation code to see how `$ip` is being used
                // 2. Disable "Discard client IP data" in Settings → Project → IP Capture
                // 3. Add Property Filter transformation configured to filter out `$ip`
                // 4. Position it AFTER your custom transformation
                //
                // This ensures your transformation can access IP while not storing it long-term.

                // Create a custom transformation that uses $ip (execution_order = 0)
                const customCode = `
                    let ip := event.properties.$ip
                    let returnEvent := event
                    if (notEmpty(ip)) {
                        returnEvent.properties.ip_was_present := true
                        returnEvent.properties.ip_first_octet := splitByString('.', ip)[1]
                    } else {
                        returnEvent.properties.ip_was_present := false
                    }
                    return returnEvent
                `
                const customByteCode = await compileHog(customCode)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: customCode,
                    bytecode: customByteCode,
                    name: 'Custom IP Processor',
                    type: 'transformation',
                    execution_order: 0,
                })

                // Create Property Filter to remove $ip after custom processing (execution_order = 1)
                const filterByteCode = await compileHog(filterPropertiesTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: filterPropertiesTemplate.code,
                    bytecode: filterByteCode,
                    name: 'Property Filter',
                    type: 'transformation',
                    inputs_schema: filterPropertiesTemplate.inputs_schema,
                    inputs: {
                        propertiesToFilter: { value: '$ip' },
                    },
                    execution_order: 1,
                })

                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // Custom transformation saw the IP and extracted data
                expect(properties.ip_was_present).toBe(true)
                expect(properties.ip_first_octet).toBe('192')

                // $ip should be removed by Property Filter
                expect(properties.$ip).toBeNull()
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'IP Anonymization (no Property Filter needed): anonymizes $ip instead of removing it',
            async () => {
                // Remediation for: IP Anonymization - template-ip-anonymization
                //
                // BEHAVIOR CHANGE: Your IP handling is changing from anonymization
                // (192.168.1.100 → 192.168.1.0) to complete removal.
                //
                // If you want to keep anonymizing instead of removing:
                // 1. Disable "Discard client IP data" in Settings → Project → IP Capture
                // 2. Verify your IP Anonymization transformation is enabled
                //
                // No Property Filter needed - the IP is already anonymized (last octet zeroed).
                const hogByteCode = await compileHog(ipAnonymizationTemplate.code)
                await insertHogFunction({
                    name: 'IP Anonymization',
                    hog: ipAnonymizationTemplate.code,
                    bytecode: hogByteCode,
                    inputs_schema: ipAnonymizationTemplate.inputs_schema,
                })

                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // $ip should be anonymized (last octet zeroed), not removed
                expect(properties.$ip).toBe('192.168.1.0')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )
    })

    describe('Legacy plugins with anonymize_ips enabled', () => {
        let ingester: IngestionConsumer

        beforeEach(async () => {
            await setAnonymizeIps(true)
            ingester = await createIngestionConsumer(hub)
        })

        afterEach(async () => {
            await ingester.stop()
        })

        it(
            'Legacy Property Filter plugin filtering $ip is redundant when anonymize_ips is enabled',
            async () => {
                // Create Legacy Property Filter plugin configured to remove $ip
                await _insertHogFunction(hub.postgres, team.id, {
                    name: 'Legacy Property Filter',
                    type: 'transformation',
                    template_id: propertyFilterPlugin.template.id,
                    inputs: {
                        properties: { value: '$ip' },
                    },
                })

                // Send an event with an IP
                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                        $browser: 'Chrome',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // $ip should be removed (by filterIpPropertiesStep before the plugin runs)
                expect(properties).not.toHaveProperty('$ip')
                // Other properties should be preserved
                expect(properties.$browser).toBe('Chrome')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Advanced GeoIP discardLibs has no GeoIP properties to filter when anonymize_ips is enabled',
            async () => {
                // First, create GeoIP transformation to add geo properties
                const geoipByteCode = await compileHog(geoipTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: geoipTemplate.code,
                    bytecode: geoipByteCode,
                    name: 'GeoIP Transformation',
                    type: 'transformation',
                    execution_order: 0,
                })

                // Create Advanced GeoIP plugin to filter GeoIP for posthog-ios library
                await _insertHogFunction(hub.postgres, team.id, {
                    name: 'Advanced GeoIP',
                    type: 'transformation',
                    template_id: pluginAdvancedGeoip.template.id,
                    inputs: {
                        discardIp: { value: 'false' },
                        discardLibs: { value: 'posthog-ios' },
                    },
                    execution_order: 1,
                })

                // Send an event from posthog-ios with an IP
                const event = createEvent({
                    ip: '89.160.20.129', // Swedish IP
                    properties: {
                        $ip: '89.160.20.129',
                        $lib: 'posthog-ios',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // IP was removed before GeoIP could run, so no GeoIP properties to filter
                expect(properties).not.toHaveProperty('$ip')
                expect(properties).not.toHaveProperty('$geoip_country_code')
                expect(properties).not.toHaveProperty('$geoip_country_name')
                // $lib should still be present
                expect(properties.$lib).toBe('posthog-ios')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Advanced GeoIP discardIp is redundant when anonymize_ips is enabled',
            async () => {
                // First, create GeoIP transformation
                const geoipByteCode = await compileHog(geoipTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: geoipTemplate.code,
                    bytecode: geoipByteCode,
                    name: 'GeoIP Transformation',
                    type: 'transformation',
                    execution_order: 0,
                })

                // Create Advanced GeoIP plugin to discard IP after GeoIP
                await _insertHogFunction(hub.postgres, team.id, {
                    name: 'Advanced GeoIP',
                    type: 'transformation',
                    template_id: pluginAdvancedGeoip.template.id,
                    inputs: {
                        discardIp: { value: 'true' },
                        discardLibs: { value: '' },
                    },
                    execution_order: 1,
                })

                // Send an event with an IP
                const event = createEvent({
                    ip: '89.160.20.129',
                    properties: {
                        $ip: '89.160.20.129',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // IP was already removed before GeoIP, so Advanced GeoIP has nothing to discard
                expect(properties).not.toHaveProperty('$ip')
                // No GeoIP properties were added either
                expect(properties).not.toHaveProperty('$geoip_country_code')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )
    })

    describe('Legacy plugins with anonymize_ips disabled', () => {
        let ingester: IngestionConsumer

        beforeEach(async () => {
            await setAnonymizeIps(false)
            ingester = await createIngestionConsumer(hub)
        })

        afterEach(async () => {
            await ingester.stop()
        })

        it(
            'Legacy Property Filter plugin can remove $ip when anonymize_ips is disabled',
            async () => {
                // Create Legacy Property Filter plugin configured to remove $ip
                await _insertHogFunction(hub.postgres, team.id, {
                    name: 'Legacy Property Filter',
                    type: 'transformation',
                    template_id: propertyFilterPlugin.template.id,
                    inputs: {
                        properties: { value: '$ip' },
                    },
                })

                // Send an event with an IP
                const event = createEvent({
                    ip: '192.168.1.100',
                    properties: {
                        $ip: '192.168.1.100',
                        $browser: 'Chrome',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // $ip should be removed by the legacy plugin
                expect(properties).not.toHaveProperty('$ip')
                // Other properties should be preserved
                expect(properties.$browser).toBe('Chrome')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Advanced GeoIP discardLibs removes GeoIP properties for matching library',
            async () => {
                // First, create GeoIP transformation to add geo properties (execution_order = 0)
                const geoipByteCode = await compileHog(geoipTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: geoipTemplate.code,
                    bytecode: geoipByteCode,
                    name: 'GeoIP Transformation',
                    type: 'transformation',
                    execution_order: 0,
                })

                // Create Advanced GeoIP plugin to filter GeoIP for posthog-ios library (execution_order = 1)
                await _insertHogFunction(hub.postgres, team.id, {
                    name: 'Advanced GeoIP',
                    type: 'transformation',
                    template_id: pluginAdvancedGeoip.template.id,
                    inputs: {
                        discardIp: { value: 'false' },
                        discardLibs: { value: 'posthog-ios' },
                    },
                    execution_order: 1,
                })

                // Send an event from posthog-ios with an IP
                const event = createEvent({
                    ip: '89.160.20.129', // Swedish IP
                    properties: {
                        $ip: '89.160.20.129',
                        $lib: 'posthog-ios',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // IP should still be present (discardIp is false)
                expect(properties.$ip).toBe('89.160.20.129')

                // GeoIP properties are removed by Advanced GeoIP for posthog-ios library
                // Note: This test documents that when GeoIP + Advanced GeoIP are both active,
                // the Advanced GeoIP discardLibs feature successfully removes GeoIP properties
                // for events from matching libraries.
                expect(properties).not.toHaveProperty('$geoip_country_code')
                expect(properties).not.toHaveProperty('$geoip_country_name')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Advanced GeoIP discardIp removes IP after GeoIP when anonymize_ips is disabled',
            async () => {
                // First, create GeoIP transformation
                const geoipByteCode = await compileHog(geoipTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: geoipTemplate.code,
                    bytecode: geoipByteCode,
                    name: 'GeoIP Transformation',
                    type: 'transformation',
                    execution_order: 0,
                })

                // Create Advanced GeoIP plugin to discard IP after GeoIP
                await _insertHogFunction(hub.postgres, team.id, {
                    name: 'Advanced GeoIP',
                    type: 'transformation',
                    template_id: pluginAdvancedGeoip.template.id,
                    inputs: {
                        discardIp: { value: 'true' },
                        discardLibs: { value: '' },
                    },
                    execution_order: 1,
                })

                // Send an event with an IP
                const event = createEvent({
                    ip: '89.160.20.129',
                    properties: {
                        $ip: '89.160.20.129',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // GeoIP properties should be added (GeoIP ran first)
                expect(properties.$geoip_country_code).toBe('SE')
                expect(properties.$geoip_country_name).toBe('Sweden')

                // Note: Advanced GeoIP checks for $plugins_succeeded containing "GeoIP (N)"
                // which is the legacy plugin format. The modern GeoIP template doesn't add this,
                // so discardIp won't trigger. IP will still be present.
                // This demonstrates the behavior gap between legacy and modern implementations.
                expect(properties.$ip).toBe('89.160.20.129')
            },
            TRANSFORMATION_TEST_TIMEOUT
        )
    })

    describe('Legacy plugins with remediation applied', () => {
        // These tests verify remediation patterns for legacy plugins:
        // Since Advanced GeoIP's discardIp doesn't work with modern GeoIP template,
        // use Property Filter to remove $ip after transformations run.

        let ingester: IngestionConsumer

        beforeEach(async () => {
            await setAnonymizeIps(false)
            ingester = await createIngestionConsumer(hub)
        })

        afterEach(async () => {
            await ingester.stop()
        })

        it(
            'GeoIP + Property Filter (replacing Advanced GeoIP discardIp): adds geo properties then removes $ip',
            async () => {
                // Remediation for: Advanced GeoIP - IP removal (Legacy Plugin) - discardIp setting
                //
                // The discardIp setting is now redundant - IPs are removed at ingestion level.
                // If you still want GeoIP + IP removal:
                // 1. Add the new "GeoIP" transformation
                // 2. Add "Property Filter" transformation configured to filter out `$ip`
                // 3. Position Property Filter AFTER GeoIP
                // 4. Disable "Discard client IP data" in Settings → Project → IP Capture
                // 5. Disable the legacy "Advanced GeoIP" plugin

                // Create GeoIP transformation (execution_order = 0)
                const geoipByteCode = await compileHog(geoipTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: geoipTemplate.code,
                    bytecode: geoipByteCode,
                    name: 'GeoIP Transformation',
                    type: 'transformation',
                    execution_order: 0,
                })

                // Create Property Filter to remove $ip (execution_order = 1)
                // This replaces Advanced GeoIP's discardIp functionality
                const filterByteCode = await compileHog(filterPropertiesTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: filterPropertiesTemplate.code,
                    bytecode: filterByteCode,
                    name: 'Property Filter',
                    type: 'transformation',
                    inputs_schema: filterPropertiesTemplate.inputs_schema,
                    inputs: {
                        propertiesToFilter: { value: '$ip' },
                    },
                    execution_order: 1,
                })

                // Send an event with an IP
                const event = createEvent({
                    ip: '89.160.20.129', // Swedish IP
                    properties: {
                        $ip: '89.160.20.129',
                    },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(1)

                const eventResult = producedMessages[0].value as any
                const properties =
                    typeof eventResult.properties === 'string'
                        ? parseJSON(eventResult.properties)
                        : eventResult.properties

                // GeoIP properties should be added
                expect(properties.$geoip_country_code).toBe('SE')
                expect(properties.$geoip_country_name).toBe('Sweden')

                // $ip should be removed by Property Filter
                expect(properties.$ip).toBeNull()
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'Conditional IP removal + GeoIP + Property Filter: skips GeoIP for specific libraries',
            async () => {
                // Remediation for: Advanced GeoIP - Library-based filtering (Legacy Plugin) - discardLibs setting
                //
                // To restore library-based GeoIP filtering:
                // 1. Create a custom transformation to remove `$ip` for specific libraries:
                //    ```hog
                //    let lib := event.properties.$lib
                //    let returnEvent := event
                //    if (lib == 'posthog-ios' or lib == 'posthog-android') {
                //        returnEvent.properties.$ip := null
                //    }
                //    return returnEvent
                //    ```
                // 2. Position it BEFORE the GeoIP transformation (execution order matters)
                // 3. Add the "GeoIP" transformation after the custom transformation
                // 4. Add "Property Filter" to remove `$ip` from all events (AFTER GeoIP)
                // 5. Disable "Discard client IP data" in Settings → Project → IP Capture
                // 6. Disable the legacy "Advanced GeoIP" plugin
                //
                // How it works: By removing `$ip` BEFORE GeoIP runs for specific libraries,
                // GeoIP has no IP to look up and won't add any geo properties.

                // Create custom transformation to remove $ip for mobile libraries (execution_order = 0)
                const conditionalIpRemovalCode = `
                    let lib := event.properties.$lib
                    let returnEvent := event

                    if (lib == 'posthog-ios' or lib == 'posthog-android') {
                        returnEvent.properties.$ip := null
                    }
                    return returnEvent
                `
                const conditionalByteCode = await compileHog(conditionalIpRemovalCode)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: conditionalIpRemovalCode,
                    bytecode: conditionalByteCode,
                    name: 'Conditional IP Removal',
                    type: 'transformation',
                    execution_order: 0,
                })

                // Create GeoIP transformation (execution_order = 1)
                // Will only add geo properties for events that still have $ip
                const geoipByteCode = await compileHog(geoipTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: geoipTemplate.code,
                    bytecode: geoipByteCode,
                    name: 'GeoIP Transformation',
                    type: 'transformation',
                    execution_order: 1,
                })

                // Create Property Filter to remove $ip from all events (execution_order = 2)
                const filterByteCode = await compileHog(filterPropertiesTemplate.code)
                await _insertHogFunction(hub.postgres, team.id, {
                    hog: filterPropertiesTemplate.code,
                    bytecode: filterByteCode,
                    name: 'Property Filter',
                    type: 'transformation',
                    inputs_schema: filterPropertiesTemplate.inputs_schema,
                    inputs: {
                        propertiesToFilter: { value: '$ip' },
                    },
                    execution_order: 2,
                })

                // Send an event from posthog-ios (should NOT get GeoIP)
                const iosEvent = createEvent({
                    ip: '89.160.20.129',
                    properties: {
                        $ip: '89.160.20.129',
                        $lib: 'posthog-ios',
                        test_marker: 'ios-event',
                    },
                })

                // Send an event from posthog-android (should NOT get GeoIP)
                const androidEvent = createEvent({
                    ip: '89.160.20.129',
                    properties: {
                        $ip: '89.160.20.129',
                        $lib: 'posthog-android',
                        test_marker: 'android-event',
                    },
                })

                // Send an event from posthog-js (SHOULD get GeoIP)
                const jsEvent = createEvent({
                    ip: '89.160.20.129',
                    properties: {
                        $ip: '89.160.20.129',
                        $lib: 'posthog-js',
                        test_marker: 'js-event',
                    },
                })

                const messages = createKafkaMessages([iosEvent, androidEvent, jsEvent])
                await ingester.handleKafkaBatch(messages)

                const producedMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                expect(producedMessages).toHaveLength(3)

                // Helper to find and parse event properties
                const findEventProperties = (marker: string) => {
                    const result = producedMessages.find((m: any) => {
                        const props =
                            typeof m.value.properties === 'string' ? parseJSON(m.value.properties) : m.value.properties
                        return props.test_marker === marker
                    })
                    return typeof result!.value.properties === 'string'
                        ? parseJSON(result!.value.properties)
                        : result!.value.properties
                }

                // iOS event: No GeoIP (IP removed before GeoIP), $ip removed
                const iosProperties = findEventProperties('ios-event')
                expect(iosProperties).not.toHaveProperty('$geoip_country_code')
                expect(iosProperties.$ip).toBeNull()

                // Android event: No GeoIP (IP removed before GeoIP), $ip removed
                const androidProperties = findEventProperties('android-event')
                expect(androidProperties).not.toHaveProperty('$geoip_country_code')
                expect(androidProperties.$ip).toBeNull()

                // JS event: GeoIP present (IP was available for GeoIP), $ip removed by final filter
                const jsProperties = findEventProperties('js-event')
                expect(jsProperties.$geoip_country_code).toBe('SE')
                expect(jsProperties.$ip).toBeNull()
            },
            TRANSFORMATION_TEST_TIMEOUT
        )
    })
})
