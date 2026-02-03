import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    EVENT_GROUP_TYPES,
    PROPERTY_GROUP_TYPES,
    RecentItem,
    recentItemsLogic,
} from './recentItemsLogic'
import { TaxonomicFilterGroupType } from './types'

describe('recentItemsLogic', () => {
    let logic: ReturnType<typeof recentItemsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = recentItemsLogic()
        logic.mount()
        // Clear any persisted state
        logic.actions.clearRecentEvents()
        logic.actions.clearRecentProperties()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('EVENT_GROUP_TYPES and PROPERTY_GROUP_TYPES', () => {
        it('defines event-like group types', () => {
            expect(EVENT_GROUP_TYPES).toContain(TaxonomicFilterGroupType.Events)
            expect(EVENT_GROUP_TYPES).toContain(TaxonomicFilterGroupType.CustomEvents)
            expect(EVENT_GROUP_TYPES).toContain(TaxonomicFilterGroupType.Actions)
            expect(EVENT_GROUP_TYPES).not.toContain(TaxonomicFilterGroupType.EventProperties)
        })

        it('defines property-like group types', () => {
            expect(PROPERTY_GROUP_TYPES).toContain(TaxonomicFilterGroupType.EventProperties)
            expect(PROPERTY_GROUP_TYPES).toContain(TaxonomicFilterGroupType.PersonProperties)
            expect(PROPERTY_GROUP_TYPES).toContain(TaxonomicFilterGroupType.SessionProperties)
            expect(PROPERTY_GROUP_TYPES).not.toContain(TaxonomicFilterGroupType.Events)
        })
    })

    describe('recentEvents', () => {
        const createEventItem = (name: string, value: string | number): RecentItem => ({
            type: TaxonomicFilterGroupType.Events,
            value,
            name,
            timestamp: Date.now(),
        })

        it('starts with empty list', async () => {
            await expectLogic(logic).toMatchValues({
                recentEvents: [],
                recentEventOptions: [],
            })
        })

        it('adds event to recent events', async () => {
            const item = createEventItem('$pageview', '$pageview')

            await expectLogic(logic, () => {
                logic.actions.addRecentEvent(item)
            }).toMatchValues({
                recentEvents: [item],
                recentEventOptions: [item],
            })
        })

        it('adds multiple events maintaining order (most recent first)', async () => {
            const item1 = createEventItem('$pageview', '$pageview')
            const item2 = createEventItem('$autocapture', '$autocapture')
            const item3 = createEventItem('custom_event', 'custom_event')

            logic.actions.addRecentEvent(item1)
            logic.actions.addRecentEvent(item2)
            logic.actions.addRecentEvent(item3)

            await expectLogic(logic).toMatchValues({
                recentEvents: [item3, item2, item1],
            })
        })

        it('deduplicates items by value and type', async () => {
            const item1 = createEventItem('$pageview', '$pageview')
            const item2Updated = { ...createEventItem('$pageview', '$pageview'), timestamp: Date.now() + 1000 }

            logic.actions.addRecentEvent(item1)
            logic.actions.addRecentEvent(item2Updated)

            await expectLogic(logic).toMatchValues({
                recentEvents: [item2Updated],
            })
        })

        it('limits to 20 items maximum', async () => {
            const items: RecentItem[] = []
            for (let i = 0; i < 25; i++) {
                const item = createEventItem(`event_${i}`, `event_${i}`)
                items.push(item)
                logic.actions.addRecentEvent(item)
            }

            const { recentEvents } = logic.values
            expect(recentEvents.length).toBe(20)
            expect(recentEvents[0].name).toBe('event_24')
            expect(recentEvents[19].name).toBe('event_5')
        })

        it('clears recent events', async () => {
            const item = createEventItem('$pageview', '$pageview')
            logic.actions.addRecentEvent(item)

            await expectLogic(logic, () => {
                logic.actions.clearRecentEvents()
            }).toMatchValues({
                recentEvents: [],
            })
        })

        it('does not affect recent properties when adding events', async () => {
            const eventItem = createEventItem('$pageview', '$pageview')
            const propertyItem: RecentItem = {
                type: TaxonomicFilterGroupType.EventProperties,
                value: '$browser',
                name: '$browser',
                timestamp: Date.now(),
            }

            logic.actions.addRecentProperty(propertyItem)
            logic.actions.addRecentEvent(eventItem)

            await expectLogic(logic).toMatchValues({
                recentEvents: [eventItem],
                recentProperties: [propertyItem],
            })
        })
    })

    describe('recentProperties', () => {
        const createPropertyItem = (name: string, value: string): RecentItem => ({
            type: TaxonomicFilterGroupType.EventProperties,
            value,
            name,
            timestamp: Date.now(),
        })

        it('starts with empty list', async () => {
            await expectLogic(logic).toMatchValues({
                recentProperties: [],
                recentPropertyOptions: [],
            })
        })

        it('adds property to recent properties', async () => {
            const item = createPropertyItem('$browser', '$browser')

            await expectLogic(logic, () => {
                logic.actions.addRecentProperty(item)
            }).toMatchValues({
                recentProperties: [item],
                recentPropertyOptions: [item],
            })
        })

        it('adds multiple properties maintaining order (most recent first)', async () => {
            const item1 = createPropertyItem('$browser', '$browser')
            const item2 = createPropertyItem('$os', '$os')
            const item3 = createPropertyItem('$device_type', '$device_type')

            logic.actions.addRecentProperty(item1)
            logic.actions.addRecentProperty(item2)
            logic.actions.addRecentProperty(item3)

            await expectLogic(logic).toMatchValues({
                recentProperties: [item3, item2, item1],
            })
        })

        it('deduplicates items by value and type', async () => {
            const item1 = createPropertyItem('$browser', '$browser')
            const item2Updated = { ...createPropertyItem('$browser', '$browser'), timestamp: Date.now() + 1000 }

            logic.actions.addRecentProperty(item1)
            logic.actions.addRecentProperty(item2Updated)

            await expectLogic(logic).toMatchValues({
                recentProperties: [item2Updated],
            })
        })

        it('allows same value with different types', async () => {
            const eventProp: RecentItem = {
                type: TaxonomicFilterGroupType.EventProperties,
                value: 'name',
                name: 'name',
                timestamp: Date.now(),
            }
            const personProp: RecentItem = {
                type: TaxonomicFilterGroupType.PersonProperties,
                value: 'name',
                name: 'name',
                timestamp: Date.now() + 100,
            }

            logic.actions.addRecentProperty(eventProp)
            logic.actions.addRecentProperty(personProp)

            await expectLogic(logic).toMatchValues({
                recentProperties: [personProp, eventProp],
            })
        })

        it('limits to 20 items maximum', async () => {
            const items: RecentItem[] = []
            for (let i = 0; i < 25; i++) {
                const item = createPropertyItem(`property_${i}`, `property_${i}`)
                items.push(item)
                logic.actions.addRecentProperty(item)
            }

            const { recentProperties } = logic.values
            expect(recentProperties.length).toBe(20)
            expect(recentProperties[0].name).toBe('property_24')
            expect(recentProperties[19].name).toBe('property_5')
        })

        it('clears recent properties', async () => {
            const item = createPropertyItem('$browser', '$browser')
            logic.actions.addRecentProperty(item)

            await expectLogic(logic, () => {
                logic.actions.clearRecentProperties()
            }).toMatchValues({
                recentProperties: [],
            })
        })
    })

    describe('selectors', () => {
        it('recentEventOptions returns all recent events', async () => {
            const item1: RecentItem = {
                type: TaxonomicFilterGroupType.Events,
                value: '$pageview',
                name: '$pageview',
                timestamp: Date.now(),
            }
            const item2: RecentItem = {
                type: TaxonomicFilterGroupType.Actions,
                value: 1,
                name: 'Sign Up Action',
                timestamp: Date.now() + 100,
            }

            logic.actions.addRecentEvent(item1)
            logic.actions.addRecentEvent(item2)

            await expectLogic(logic).toMatchValues({
                recentEventOptions: [item2, item1],
            })
        })

        it('recentPropertyOptions returns all recent properties', async () => {
            const item1: RecentItem = {
                type: TaxonomicFilterGroupType.EventProperties,
                value: '$browser',
                name: '$browser',
                timestamp: Date.now(),
            }
            const item2: RecentItem = {
                type: TaxonomicFilterGroupType.PersonProperties,
                value: 'email',
                name: 'email',
                timestamp: Date.now() + 100,
            }

            logic.actions.addRecentProperty(item1)
            logic.actions.addRecentProperty(item2)

            await expectLogic(logic).toMatchValues({
                recentPropertyOptions: [item2, item1],
            })
        })
    })
})
