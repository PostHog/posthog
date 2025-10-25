import { initKeaTests } from '~/test/init'
import '~/types'

import { GroupsNewLogicProps, flattenProperties, groupsNewLogic } from './groupsNewLogic'

describe('groupsNewLogic', () => {
    let logic: ReturnType<typeof groupsNewLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('initial state and props', () => {
        it('initializes with correct default state', () => {
            const props: GroupsNewLogicProps = { groupTypeIndex: 1 }
            logic = groupsNewLogic(props)
            logic.mount()

            expect(logic.values.logicProps).toEqual(props)
            expect(logic.values.createdGroup).toBeNull()
            expect(logic.values.group).toEqual({})
        })

        it('handles different groupTypeIndex values', () => {
            const testCases = [0, 1, 2, 4]

            testCases.forEach((groupTypeIndex) => {
                const testLogic = groupsNewLogic({ groupTypeIndex })
                testLogic.mount()

                expect(testLogic.values.logicProps.groupTypeIndex).toBe(groupTypeIndex)

                testLogic.unmount()
            })
        })
    })

    describe('form logic', () => {
        beforeEach(() => {
            const props: GroupsNewLogicProps = { groupTypeIndex: 1 }
            logic = groupsNewLogic(props)
            logic.mount()
        })

        it('handles form validation correctly', () => {
            logic.actions.submitGroup()

            expect(logic.values.groupHasErrors).toBe(true)
            expect(logic.values.groupErrors.name).toBe('Group name cannot be empty')
            expect(logic.values.groupErrors.group_key).toBe('Group key cannot be empty')

            logic.actions.setGroupValue('name', 'Valid Name')
            logic.actions.setGroupValue('group_key', 'valid-key')

            expect(logic.values.groupHasErrors).toBe(false)
            expect(logic.values.groupErrors).toEqual({})
        })

        it('resets form state', () => {
            logic.actions.setGroupValue('name', 'Test Name')
            logic.actions.addFormProperty()

            expect(logic.values.group.name).toBe('Test Name')
            expect(logic.values.group.customProperties).toHaveLength(1)

            logic.actions.resetGroup()

            expect(logic.values.createdGroup).toBeNull()
            expect(logic.values.group.customProperties).toBe(undefined)
        })
    })

    describe('custom properties management', () => {
        beforeEach(() => {
            const props: GroupsNewLogicProps = { groupTypeIndex: 1 }
            logic = groupsNewLogic(props)
            logic.mount()
        })

        it('should add a new property', () => {
            expect(logic.values.group.customProperties).toBe(undefined)

            logic.actions.addFormProperty()

            expect(logic.values.group.customProperties).toEqual([{ name: '', type: 'string', value: '' }])
        })

        it('should add multiple properties', () => {
            logic.actions.addFormProperty()

            expect(logic.values.group.customProperties).toEqual([{ name: '', type: 'string', value: '' }])

            logic.actions.addFormProperty()

            expect(logic.values.group.customProperties).toEqual([
                { name: '', type: 'string', value: '' },
                { name: '', type: 'string', value: '' },
            ])
        })

        it('should update property name and value', () => {
            logic.actions.addFormProperty()

            logic.actions.setGroupValue('customProperties', [{ name: 'test-property', type: 'string', value: '' }])

            expect(logic.values.group.customProperties[0]).toMatchObject({
                name: 'test-property',
                type: 'string',
                value: '',
            })

            logic.actions.setGroupValue('customProperties', [
                { name: 'test-property', type: 'string', value: 'test-value' },
            ])

            expect(logic.values.group.customProperties[0]).toMatchObject({
                name: 'test-property',
                type: 'string',
                value: 'test-value',
            })
        })

        it('should handle multiple properties with updates', () => {
            logic.actions.setGroupValue('customProperties', [
                { name: 'zero', type: 'string', value: '' },
                { name: 'one', type: 'string', value: '' },
                { name: 'two', type: 'string', value: '' },
            ])

            expect(logic.values.group.customProperties).toEqual([
                { name: 'zero', type: 'string', value: '' },
                { name: 'one', type: 'string', value: '' },
                { name: 'two', type: 'string', value: '' },
            ])
        })

        it('should remove a property', () => {
            // Add some properties first
            logic.actions.setGroupValue('customProperties', [
                { name: 'prop1', type: 'string', value: 'value1' },
                { name: 'prop2', type: 'string', value: 'value2' },
            ])

            expect(logic.values.group.customProperties).toHaveLength(2)

            // Remove the first property
            logic.actions.removeFormProperty(0)

            expect(logic.values.group.customProperties).toEqual([{ name: 'prop2', type: 'string', value: 'value2' }])
        })

        it('should handle edge cases for property updates gracefully', () => {
            logic.actions.addFormProperty()
            // Test bounds - trying to update non-existent property
            const currentProps = logic.values.group.customProperties || []
            logic.actions.setGroupValue('customProperties', currentProps)
            expect(logic.values.group.customProperties?.[5]).toBeUndefined()
        })
    })

    describe('form validation', () => {
        beforeEach(() => {
            const props: GroupsNewLogicProps = { groupTypeIndex: 1 }
            logic = groupsNewLogic(props)
            logic.mount()
        })

        it('should validate empty custom property names', () => {
            logic.actions.setGroupValue('name', 'Valid Name')
            logic.actions.setGroupValue('group_key', 'valid-key')
            logic.actions.addFormProperty()

            logic.actions.submitGroup()

            expect(logic.values.groupHasErrors).toBe(true)
            expect(logic.values.groupErrors?.customProperties?.[0]?.name).toBe('Property name cannot be empty')
        })

        it('should validate duplicate custom property names', () => {
            logic.actions.setGroupValue('name', 'Valid Name')
            logic.actions.setGroupValue('group_key', 'valid-key')
            logic.actions.setGroupValue('customProperties', [
                { name: 'duplicate', type: 'string', value: '' },
                { name: 'duplicate', type: 'string', value: '' },
            ])

            logic.actions.submitGroup()

            expect(logic.values.groupHasErrors).toBe(true)
            expect(logic.values.groupErrors?.customProperties?.[0]?.name).toBe('Property name must be unique')
            expect(logic.values.groupErrors?.customProperties?.[1]?.name).toBe('Property name must be unique')
        })

        it('should validate reserved property name "name"', () => {
            logic.actions.setGroupValue('name', 'Valid Name')
            logic.actions.setGroupValue('group_key', 'valid-key')
            logic.actions.setGroupValue('customProperties', [{ name: 'name', type: 'string', value: '' }])

            logic.actions.submitGroup()

            expect(logic.values.groupHasErrors).toBe(true)
            expect(logic.values.groupErrors?.customProperties?.[0]?.name).toBe('Property name "name" is reserved')
        })

        it('should pass validation with valid custom properties', () => {
            logic.actions.setGroupValue('name', 'Valid Name')
            logic.actions.setGroupValue('group_key', 'valid-key')
            logic.actions.setGroupValue('customProperties', [
                { name: 'company', type: 'string', value: 'PostHog' },
                { name: 'industry', type: 'string', value: 'Analytics' },
            ])

            expect(logic.values.groupHasErrors).toBe(false)
            expect(logic.values.groupErrors?.customProperties).toBeUndefined()
        })
    })

    describe('form submission', () => {
        beforeEach(() => {
            const props: GroupsNewLogicProps = { groupTypeIndex: 1 }
            logic = groupsNewLogic(props)
            logic.mount()
        })

        it('should submit form with custom properties', () => {
            const saveGroupSpy = jest.spyOn(logic.actions, 'saveGroup')

            logic.actions.setGroupValue('name', 'Test Group')
            logic.actions.setGroupValue('group_key', 'test-key')
            logic.actions.setGroupValue('customProperties', [{ name: 'test-prop', type: 'string', value: '' }])

            logic.actions.submitGroup()

            expect(saveGroupSpy).toHaveBeenCalledWith({
                group_key: 'test-key',
                group_type_index: 1,
                group_properties: {
                    name: 'Test Group',
                },
            })
        })
    })

    describe('property handling edge cases', () => {
        beforeEach(() => {
            const props: GroupsNewLogicProps = { groupTypeIndex: 1 }
            logic = groupsNewLogic(props)
            logic.mount()
        })

        it('should handle special characters in property names and values', () => {
            logic.actions.setGroupValue('customProperties', [
                { name: 'special-chars!@#$%', type: 'string', value: 'value with spaces & symbols' },
            ])

            const customProperties = logic.values.group.customProperties
            expect(customProperties?.[0]).toEqual({
                name: 'special-chars!@#$%',
                type: 'string',
                value: 'value with spaces & symbols',
            })
        })
    })
})

describe('flattenProperties', () => {
    it('filters out empty properties during form submission', () => {
        const rawProperties = [
            { name: '', type: 'string' as const, value: '' },
            { name: ' ', type: 'string' as const, value: ' ' },
            { name: 'valid-prop', type: 'string' as const, value: 'valid-value' },
            { name: 'another-valid-prop', type: 'string' as const, value: 'valid-value ' },
            { name: '', type: 'string' as const, value: 'orphaned-value' },
        ]

        const flattenedProperties = flattenProperties(rawProperties)

        expect(flattenedProperties).toEqual({ 'valid-prop': 'valid-value', 'another-valid-prop': 'valid-value ' })
    })

    it('handles boolean properties correctly', () => {
        const rawProperties = [
            { name: 'is_active', type: 'boolean' as const, value: 'true' },
            { name: 'has_subscription', type: 'boolean' as const, value: 'false' },
            { name: 'is_null', type: 'boolean' as const, value: 'null' },
        ]

        const flattenedProperties = flattenProperties(rawProperties)

        expect(flattenedProperties).toEqual({
            is_active: true,
            has_subscription: false,
            is_null: null,
        })
    })

    it('converts numeric strings to numbers for string type properties', () => {
        const rawProperties = [
            { name: 'count', type: 'string' as const, value: '42' },
            { name: 'price', type: 'string' as const, value: '19.99' },
            { name: 'name', type: 'string' as const, value: 'PostHog' },
            { name: 'zero', type: 'string' as const, value: '0' },
        ]

        const flattenedProperties = flattenProperties(rawProperties)

        expect(flattenedProperties).toEqual({
            count: 42,
            price: 19.99,
            name: 'PostHog',
            zero: 0,
        })
    })
})
