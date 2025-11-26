import { render } from '@testing-library/react'

import { ActivityChange, ChangeMapping, Description } from 'lib/components/ActivityLog/humanizeActivity'

import { ActionsNode, CustomerAnalyticsConfig, EventsNode, NodeKind } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { customerAnalyticsConfigurationDescriber } from './customerAnalyticsConfigurationDescriber'

const getTextContent = (result: ChangeMapping | null): string | string[] => {
    const descriptions = result?.description
    if (!descriptions) {
        return ''
    }
    if (descriptions.length === 1) {
        return getDescriptionText(descriptions[0])
    }
    return descriptions.map((description) => getDescriptionText(description))
}

const getDescriptionText = (description: Description): string => {
    if (!description) {
        return ''
    }
    if (typeof description === 'string') {
        return description
    }
    const { container } = render(description)
    return container.textContent || ''
}

const createEventsNode = (event: string): EventsNode => ({
    kind: NodeKind.EventsNode,
    event,
})

const createActionsNode = (id: number): ActionsNode => ({
    kind: NodeKind.ActionsNode,
    id,
})

const createEmptyConfig = (): CustomerAnalyticsConfig => ({
    activity_event: {} as any,
    signup_pageview_event: {} as any,
    signup_event: {} as any,
    subscription_event: {} as any,
    payment_event: {} as any,
})

const createConfig = (overrides?: Partial<CustomerAnalyticsConfig>): CustomerAnalyticsConfig => ({
    ...createEmptyConfig(),
    ...overrides,
})

const createChange = (before: CustomerAnalyticsConfig, after: CustomerAnalyticsConfig): ActivityChange => ({
    type: ActivityScope.TEAM,
    action: 'changed',
    before,
    after,
})

describe('customerAnalyticsConfigurationDescriber', () => {
    describe('no changes', () => {
        it('returns null when change is undefined', () => {
            const result = customerAnalyticsConfigurationDescriber(undefined)
            expect(result).toBeNull()
        })

        it('returns null when change is null', () => {
            const result = customerAnalyticsConfigurationDescriber(null as any)
            expect(result).toBeNull()
        })

        it('returns empty description when both configs are empty', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(createEmptyConfig(), createEmptyConfig())
            )
            expect(result?.description).toEqual([])
        })

        it('returns empty description when configs are identical with events', () => {
            const config = createConfig({
                activity_event: createEventsNode('$pageview'),
                signup_event: createEventsNode('signup_completed'),
            })
            const result = customerAnalyticsConfigurationDescriber(createChange(config, config))
            expect(result?.description).toEqual([])
        })

        it('returns empty description when configs are identical with actions', () => {
            const config = createConfig({
                activity_event: createActionsNode(1),
                payment_event: createActionsNode(2),
            })
            const result = customerAnalyticsConfigurationDescriber(createChange(config, config))
            expect(result?.description).toEqual([])
        })
    })

    describe('first configuration (empty → configured)', () => {
        it('describes setting the first event', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createEmptyConfig(),
                    createConfig({
                        activity_event: createEventsNode('user_activity'),
                    })
                )
            )
            expect(result!.description).toHaveLength(1)
            expect(getTextContent(result)).toBe(
                'started configuring Customer analytics by setting Activity event to user_activity'
            )
        })

        it('describes setting the first action', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createEmptyConfig(),
                    createConfig({
                        signup_event: createActionsNode(42),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe(
                'started configuring Customer analytics by setting Signup event to Action #42'
            )
        })

        it('shows only first event when multiple are configured initially', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createEmptyConfig(),
                    createConfig({
                        activity_event: createEventsNode('activity'),
                        signup_event: createEventsNode('signup'),
                        payment_event: createActionsNode(10),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe(
                'started configuring Customer analytics by setting Activity event to activity'
            )
        })

        it('handles "All events" special case', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createEmptyConfig(),
                    createConfig({
                        activity_event: createEventsNode(''),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe(
                'started configuring Customer analytics by setting Activity event to All events'
            )
        })
    })

    describe('complete removal (configured → empty)', () => {
        it('describes removing all configuration with single event', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: createEventsNode('activity'),
                    }),
                    createEmptyConfig()
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe('removed Customer analytics configuration for Activity event: activity')
        })

        it('describes removing all configuration with multiple events', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: createEventsNode('activity'),
                        signup_event: createActionsNode(1),
                        payment_event: createEventsNode('payment'),
                    }),
                    createEmptyConfig()
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe('removed Customer analytics configuration for Activity event: activity')
        })
    })

    describe('adding events to existing configuration', () => {
        it('describes adding a single event', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: createEventsNode('activity'),
                    }),
                    createConfig({
                        activity_event: createEventsNode('activity'),
                        signup_event: createEventsNode('signup'),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe('added Signup event: signup')
        })

        it('describes adding multiple events', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: createEventsNode('activity'),
                    }),
                    createConfig({
                        activity_event: createEventsNode('activity'),
                        signup_event: createEventsNode('signup'),
                        payment_event: createActionsNode(5),
                    })
                )
            )
            expect(result?.description).toHaveLength(2)
            const descriptions = getTextContent(result)
            expect(descriptions).toContain('added Signup event: signup')
            expect(descriptions).toContain('added Payment event: Action #5')
        })
    })

    describe('removing events from configuration', () => {
        it('describes removing a single event while keeping others', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: createEventsNode('activity'),
                        signup_event: createEventsNode('signup'),
                    }),
                    createConfig({
                        activity_event: createEventsNode('activity'),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe('removed Signup event: signup')
        })

        it('describes removing multiple events', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: createEventsNode('activity'),
                        signup_event: createEventsNode('signup'),
                        payment_event: createActionsNode(10),
                    }),
                    createConfig({
                        activity_event: createEventsNode('activity'),
                    })
                )
            )
            expect(result?.description).toHaveLength(2)
            const descriptions = getTextContent(result)
            expect(descriptions).toContain('removed Signup event: signup')
            expect(descriptions).toContain('removed Payment event: Action #10')
        })
    })

    describe('changing event configurations', () => {
        it('describes changing an event to a different event', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: createEventsNode('old_activity'),
                    }),
                    createConfig({
                        activity_event: createEventsNode('new_activity'),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe('changed Activity event from old_activity to new_activity')
        })

        it('describes changing from event to action', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        subscription_event: createEventsNode('subscription'),
                    }),
                    createConfig({
                        subscription_event: createActionsNode(42),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe('changed Subscription event from subscription to Action #42')
        })

        it('describes changing from action to event', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        payment_event: createActionsNode(10),
                    }),
                    createConfig({
                        payment_event: createEventsNode('payment_completed'),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe('changed Payment event from Action #10 to payment_completed')
        })

        it('describes changing between different actions', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        signup_event: createActionsNode(1),
                    }),
                    createConfig({
                        signup_event: createActionsNode(2),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe('changed Signup event from Action #1 to Action #2')
        })

        it('describes changing to "All events"', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: createEventsNode('specific_event'),
                    }),
                    createConfig({
                        activity_event: createEventsNode(''),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe('changed Activity event from specific_event to All events')
        })
    })

    describe('partial updates (complex scenarios)', () => {
        it('handles mix of additions, removals, and changes', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: createEventsNode('old_activity'),
                        signup_event: createEventsNode('signup'),
                        payment_event: createActionsNode(1),
                    }),
                    createConfig({
                        activity_event: createEventsNode('new_activity'), // changed
                        // signup_event removed
                        payment_event: createActionsNode(1), // unchanged
                        subscription_event: createEventsNode('new_subscription'), // added
                    })
                )
            )
            expect(result?.description).toHaveLength(3)
            const descriptions = getTextContent(result)
            expect(descriptions).toContain('changed Activity event from old_activity to new_activity')
            expect(descriptions).toContain('removed Signup event: signup')
            expect(descriptions).toContain('added Subscription event: new_subscription')
        })

        it('handles all event types being modified simultaneously', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: createEventsNode('act1'),
                        signup_pageview_event: createEventsNode('spv1'),
                        signup_event: createEventsNode('se1'),
                        subscription_event: createEventsNode('sub1'),
                        payment_event: createEventsNode('pay1'),
                    }),
                    createConfig({
                        activity_event: createEventsNode('act2'),
                        signup_pageview_event: createEventsNode('spv2'),
                        signup_event: createEventsNode('se2'),
                        subscription_event: createEventsNode('sub2'),
                        payment_event: createEventsNode('pay2'),
                    })
                )
            )
            expect(result?.description).toHaveLength(5)
            const descriptions = getTextContent(result)
            expect(descriptions).toContain('changed Activity event from act1 to act2')
            expect(descriptions).toContain('changed Signup pageview event from spv1 to spv2')
            expect(descriptions).toContain('changed Signup event from se1 to se2')
            expect(descriptions).toContain('changed Subscription event from sub1 to sub2')
            expect(descriptions).toContain('changed Payment event from pay1 to pay2')
        })

        it('handles invalid event configurations gracefully', () => {
            // When before has invalid config and after has valid, treat as "added"
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: { kind: 'InvalidKind' } as any,
                    }),
                    createConfig({
                        activity_event: createEventsNode('valid_event'),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe(
                'started configuring Customer analytics by setting Activity event to valid_event'
            )
        })

        it('ignores invalid configurations mixed with valid ones', () => {
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createConfig({
                        activity_event: createEventsNode('activity'),
                        signup_event: { invalid: true } as any,
                    }),
                    createConfig({
                        activity_event: createEventsNode('activity'),
                        signup_event: createEventsNode('signup'),
                    })
                )
            )
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe('added Signup event: signup')
        })

        it('maintains event type order in descriptions', () => {
            // Even if events are set in different order, they should be described
            // in the order: activity, signup_pageview, signup, subscription, payment
            const result = customerAnalyticsConfigurationDescriber(
                createChange(
                    createEmptyConfig(),
                    createConfig({
                        payment_event: createEventsNode('payment'),
                        activity_event: createEventsNode('activity'),
                        signup_event: createEventsNode('signup'),
                    })
                )
            )
            // Should show activity_event first as it's first in the eventTypes order
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe(
                'started configuring Customer analytics by setting Activity event to activity'
            )
        })
    })

    describe('edge cases', () => {
        it('handles missing before/after properties', () => {
            const result = customerAnalyticsConfigurationDescriber({} as any)
            expect(result?.description).toEqual([])
        })

        it('handles before being null', () => {
            const result = customerAnalyticsConfigurationDescriber({
                before: null,
                after: createConfig({ activity_event: createEventsNode('activity') }),
            } as any)
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe(
                'started configuring Customer analytics by setting Activity event to activity'
            )
        })

        it('handles after being null', () => {
            const result = customerAnalyticsConfigurationDescriber({
                before: createConfig({ activity_event: createEventsNode('activity') }),
                after: null,
            } as any)
            expect(result?.description).toHaveLength(1)
            expect(getTextContent(result)).toBe('removed Customer analytics configuration for Activity event: activity')
        })
    })
})
