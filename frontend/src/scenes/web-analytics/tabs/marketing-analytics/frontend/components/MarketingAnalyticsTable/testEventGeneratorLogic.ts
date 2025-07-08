import { kea, path, actions, reducers, listeners } from 'kea'
import posthog from 'posthog-js'

import type { testEventGeneratorLogicType } from './testEventGeneratorLogicType'

const STORAGE_KEY = 'posthog_marketing_analytics_test_events'

// Helper functions for localStorage
const saveEventsToStorage = (events: any[]) => {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(events))
        console.log(`JFBW: Saved ${events.length} test events to localStorage`)
    } catch (error) {
        console.error('JFBW: Failed to save events to localStorage:', error)
    }
}

const loadEventsFromStorage = (): any[] => {
    try {
        const stored = localStorage.getItem(STORAGE_KEY)
        const events = stored ? JSON.parse(stored) : []
        if (events.length > 0) {
            console.log(`JFBW: Loaded ${events.length} test events from localStorage`)
        }
        return events
    } catch (error) {
        console.error('JFBW: Failed to load events from localStorage:', error)
        return []
    }
}

export interface TestEventScenario {
    id: string
    name: string
    description: string
    events: Array<{
        event: string
        distinctId: string
        properties?: Record<string, any>
        timestamp?: string
        delayMs?: number
    }>
}

export const testEventGeneratorLogic = kea<testEventGeneratorLogicType>([
    path(['scenes', 'web-analytics', 'marketing-analytics', 'testEventGeneratorLogic']),

    actions({
        setTestMode: (enabled: boolean) => ({ enabled }),
        generateTestEvent: (
            event: string,
            distinctId: string,
            properties?: Record<string, any>,
            timestamp?: string
        ) => ({
            event,
            distinctId,
            properties,
            timestamp,
        }),
        runTestScenario: (scenario: TestEventScenario) => ({ scenario }),
        setGeneratingEvents: (generating: boolean) => ({ generating }),
        addGeneratedEvent: (event: any) => ({ event }),
        clearGeneratedEvents: true,
        setCustomEventName: (name: string) => ({ name }),
        setCustomDistinctId: (id: string) => ({ id }),
        setCustomUtmCampaign: (campaign: string) => ({ campaign }),
        setCustomUtmSource: (source: string) => ({ source }),
        setCustomUtmMedium: (medium: string) => ({ medium }),
        setCustomTimestamp: (timestamp: string) => ({ timestamp }),
        setCustomProperties: (properties: string) => ({ properties }),
        loadTestScenarios: true,
    }),

    reducers({
        testModeEnabled: [
            false,
            {
                setTestMode: (_, { enabled }) => enabled,
            },
        ],
        generatingEvents: [
            false,
            {
                setGeneratingEvents: (_, { generating }) => generating,
                runTestScenario: () => true,
            },
        ],
        generatedEvents: [
            loadEventsFromStorage() as any[],
            {
                addGeneratedEvent: (state, { event }) => {
                    const newState = [...state, event]
                    saveEventsToStorage(newState)
                    return newState
                },
                clearGeneratedEvents: () => {
                    saveEventsToStorage([])
                    return []
                },
            },
        ],
        customEventName: [
            'test_conversion',
            {
                setCustomEventName: (_, { name }) => name,
            },
        ],
        customDistinctId: [
            'test_user_1',
            {
                setCustomDistinctId: (_, { id }) => id,
            },
        ],
        customUtmCampaign: [
            'test_campaign',
            {
                setCustomUtmCampaign: (_, { campaign }) => campaign,
            },
        ],
        customUtmSource: [
            'test_source',
            {
                setCustomUtmSource: (_, { source }) => source,
            },
        ],
        customUtmMedium: [
            'test_medium',
            {
                setCustomUtmMedium: (_, { medium }) => medium,
            },
        ],
        customTimestamp: [
            '',
            {
                setCustomTimestamp: (_, { timestamp }) => timestamp,
            },
        ],
        customProperties: [
            '{\n  "revenue": 100\n}',
            {
                setCustomProperties: (_, { properties }) => properties,
            },
        ],
        testScenarios: [
            [] as TestEventScenario[],
            {
                loadTestScenarios: () => [
                    {
                        id: 'event_utm_priority',
                        name: 'Event UTM Priority',
                        description: 'Purchase with UTM data should use event UTMs, not person UTMs',
                        events: [
                            {
                                event: 'pageview',
                                distinctId: 'user_1',
                                properties: {
                                    utm_campaign: 'old_campaign',
                                    utm_source: 'old_source',
                                    utm_medium: 'old_medium',
                                },
                                delayMs: 0,
                            },
                            {
                                event: 'purchase',
                                distinctId: 'user_1',
                                properties: {
                                    utm_campaign: 'new_campaign',
                                    utm_source: 'new_source',
                                    utm_medium: 'new_medium',
                                    revenue: 100,
                                },
                                delayMs: 1000,
                            },
                        ],
                    },
                    {
                        id: 'person_utm_fallback',
                        name: 'Person UTM Fallback',
                        description: "Purchase without UTM should use person's most recent UTM data",
                        events: [
                            {
                                event: 'pageview',
                                distinctId: 'user_2',
                                properties: {
                                    utm_campaign: 'fallback_campaign',
                                    utm_source: 'fallback_source',
                                    utm_medium: 'fallback_medium',
                                },
                                delayMs: 0,
                            },
                            {
                                event: 'purchase',
                                distinctId: 'user_2',
                                properties: {
                                    revenue: 150,
                                },
                                delayMs: 1000,
                            },
                        ],
                    },
                    {
                        id: 'organic_default',
                        name: 'Organic Default',
                        description: 'Purchase without any UTM data should default to "organic"',
                        events: [
                            {
                                event: 'purchase',
                                distinctId: 'user_3',
                                properties: {
                                    revenue: 75,
                                },
                                delayMs: 0,
                            },
                        ],
                    },
                    {
                        id: 'multiple_campaigns',
                        name: 'Multiple Campaigns',
                        description: 'Test multiple users with different campaign attributions',
                        events: [
                            {
                                event: 'pageview',
                                distinctId: 'user_4',
                                properties: {
                                    utm_campaign: 'campaign_a',
                                    utm_source: 'google',
                                    utm_medium: 'cpc',
                                },
                                delayMs: 0,
                            },
                            {
                                event: 'sign_up',
                                distinctId: 'user_4',
                                delayMs: 500,
                            },
                            {
                                event: 'pageview',
                                distinctId: 'user_5',
                                properties: {
                                    utm_campaign: 'campaign_b',
                                    utm_source: 'facebook',
                                    utm_medium: 'social',
                                },
                                delayMs: 1000,
                            },
                            {
                                event: 'sign_up',
                                distinctId: 'user_5',
                                delayMs: 1500,
                            },
                            {
                                event: 'purchase',
                                distinctId: 'user_4',
                                properties: {
                                    revenue: 200,
                                },
                                delayMs: 2000,
                            },
                            {
                                event: 'purchase',
                                distinctId: 'user_5',
                                properties: {
                                    revenue: 300,
                                },
                                delayMs: 2500,
                            },
                        ],
                    },
                    {
                        id: 'utm_override_sequence',
                        name: 'UTM Override Sequence',
                        description: 'User sees multiple campaigns, purchases should use most recent person UTM',
                        events: [
                            {
                                event: 'pageview',
                                distinctId: 'user_6',
                                properties: {
                                    utm_campaign: 'first_campaign',
                                    utm_source: 'google',
                                    utm_medium: 'cpc',
                                },
                                delayMs: 0,
                            },
                            {
                                event: 'purchase',
                                distinctId: 'user_6',
                                properties: {
                                    revenue: 100,
                                },
                                delayMs: 1000,
                            },
                            {
                                event: 'pageview',
                                distinctId: 'user_6',
                                properties: {
                                    utm_campaign: 'second_campaign',
                                    utm_source: 'facebook',
                                    utm_medium: 'social',
                                },
                                delayMs: 2000,
                            },
                            {
                                event: 'purchase',
                                distinctId: 'user_6',
                                properties: {
                                    revenue: 200,
                                },
                                delayMs: 3000,
                            },
                        ],
                    },
                ],
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        generateTestEvent: async ({ event, distinctId, properties, timestamp }) => {
            const eventPayload: any = {
                event,
                properties: {
                    $timestamp: timestamp ? new Date(timestamp).toISOString() : undefined,
                    ...properties,
                },
            }

            console.log('JFBW: Generating test event:', eventPayload)

            // Override distinct_id for testing if specified
            if (distinctId && distinctId !== posthog.get_distinct_id()) {
                console.log('JFBW: Using test user', window.location.pathname + '/test')
                // Use PostHog's identify method to associate events with test user
                posthog.identify(distinctId)
                posthog.capture(
                    event,
                    {
                        ...eventPayload.properties,
                        $current_url: window.location.pathname + '/test',
                    },
                    {
                        timestamp: timestamp ? new Date(timestamp) : undefined,
                    }
                )
                // Reset back to original user after a delay
                setTimeout(() => {
                    posthog.reset()
                }, 100)
            } else {
                console.log('JFBW: Using current user', window.location.pathname + '/test')
                // Use current user's distinct_id
                posthog.capture(
                    event,
                    {
                        ...eventPayload.properties,
                        $current_url: window.location.pathname + '/test',
                    },
                    {
                        timestamp: timestamp ? new Date(timestamp) : undefined,
                    }
                )
            }

            actions.addGeneratedEvent({
                ...eventPayload,
                distinct_id: distinctId || posthog.get_distinct_id(),
                timestamp: new Date().toISOString(),
            })
        },

        runTestScenario: async ({ scenario }) => {
            console.log('JFBW: Running test scenario:', scenario.name)

            for (const eventConfig of scenario.events) {
                if (eventConfig.delayMs && eventConfig.delayMs > 0) {
                    await new Promise((resolve) => setTimeout(resolve, eventConfig.delayMs))
                }

                actions.generateTestEvent(
                    eventConfig.event,
                    eventConfig.distinctId,
                    eventConfig.properties,
                    eventConfig.timestamp
                )
            }

            actions.setGeneratingEvents(false)
        },

        setTestMode: ({ enabled }) => {
            if (enabled) {
                actions.loadTestScenarios()
                console.log('JFBW: Test mode enabled for Marketing Analytics')
            } else {
                console.log('JFBW: Test mode disabled for Marketing Analytics')
            }
        },
    })),
])
