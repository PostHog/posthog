import { initKeaTests } from '~/test/init'
import { CreateGroupParams, GroupTypeIndex } from '~/types'

import { flattenProperties, groupsNewLogic, GroupsNewLogicProps } from './groupsNewLogic'

const MOCK_CREATE_PARAMS: CreateGroupParams = {
    group_key: 'test-group-key',
    group_type_index: 0 as GroupTypeIndex,
    group_properties: {
        name: 'Test Group',
    },
}

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
            expect(logic.values.customProperties).toEqual([])
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

    describe('form management', () => {
        beforeEach(() => {
            logic = groupsNewLogic({ groupTypeIndex: 0 })
            logic.mount()
        })

        it('validates required fields correctly', () => {
            logic.actions.setGroupValue('name', '')
            logic.actions.setGroupValue('group_key', '')

            expect(logic.values.groupHasErrors).toBe(true)

            logic.actions.submitGroup()

            expect(logic.values.groupErrors.name).toBe('Group name cannot be empty')
            expect(logic.values.groupErrors.group_key).toBe('Group key cannot be empty')
        })

        it('validates whitespace-only values as invalid', () => {
            logic.actions.setGroupValue('name', '   ')
            logic.actions.setGroupValue('group_key', '\t\n  ')

            logic.actions.submitGroup()

            expect(logic.values.groupHasErrors).toBe(true)
            expect(logic.values.groupErrors.name).toBe('Group name cannot be empty')
            expect(logic.values.groupErrors.group_key).toBe('Group key cannot be empty')
        })

        it('accepts valid form data', () => {
            logic.actions.setGroupValue('name', 'Valid Name')
            logic.actions.setGroupValue('group_key', 'valid-key')

            logic.actions.submitGroup()

            expect(logic.values.groupHasErrors).toBe(false)
            expect(logic.values.groupErrors).toEqual({})
        })

        it('resets form state', () => {
            logic.actions.setGroupValue('name', 'Test Name')
            logic.actions.addProperty()

            expect(logic.values.group.name).toBe('Test Name')
            expect(logic.values.customProperties).toHaveLength(1)

            logic.actions.resetGroup()

            expect(logic.values.createdGroup).toBeNull()
            expect(logic.values.customProperties).toEqual([])
        })
    })

    describe('custom properties management', () => {
        beforeEach(() => {
            logic = groupsNewLogic({ groupTypeIndex: 0 })
            logic.mount()
        })

        it('adds properties correctly', () => {
            expect(logic.values.customProperties).toEqual([])

            logic.actions.addProperty()
            expect(logic.values.customProperties).toEqual([{ name: '', value: '' }])

            logic.actions.addProperty()
            expect(logic.values.customProperties).toEqual([
                { name: '', value: '' },
                { name: '', value: '' },
            ])
        })

        it('updates property name and value', () => {
            logic.actions.addProperty()

            logic.actions.updateProperty(0, 'name', 'test-property')
            expect(logic.values.customProperties[0]).toEqual({ name: 'test-property', value: '' })

            logic.actions.updateProperty(0, 'value', 'test-value')
            expect(logic.values.customProperties[0]).toEqual({ name: 'test-property', value: 'test-value' })
        })

        it('removes properties by index', () => {
            logic.actions.addProperty()
            logic.actions.addProperty()
            logic.actions.addProperty()
            logic.actions.updateProperty(0, 'name', 'zero')
            logic.actions.updateProperty(1, 'name', 'one')
            logic.actions.updateProperty(2, 'name', 'two')

            logic.actions.removeProperty(1)
            expect(logic.values.customProperties).toEqual([
                { name: 'zero', value: '' },
                { name: 'two', value: '' },
            ])

            logic.actions.removeProperty(0)
            expect(logic.values.customProperties).toEqual([{ name: 'two', value: '' }])
        })

        it('handles out-of-bounds removal gracefully', () => {
            logic.actions.addProperty()

            logic.actions.removeProperty(5)
            expect(logic.values.customProperties).toHaveLength(1)

            logic.actions.removeProperty(-1)
            expect(logic.values.customProperties).toHaveLength(1)
        })

        it('handles invalid property updates gracefully', () => {
            logic.actions.addProperty()
            const originalProperties = [...logic.values.customProperties]

            logic.actions.updateProperty(5, 'name', 'test')
            expect(logic.values.customProperties).toEqual(originalProperties)

            logic.actions.updateProperty(-1, 'value', 'test')
            expect(logic.values.customProperties).toEqual(originalProperties)
        })
    })

    describe('action dispatch and state management', () => {
        beforeEach(() => {
            logic = groupsNewLogic({ groupTypeIndex: 1 })
            logic.mount()
        })

        it('dispatches saveGroup action correctly', () => {
            expect(() => {
                logic.actions.saveGroup(MOCK_CREATE_PARAMS)
            }).not.toThrow()
        })

        it('initializes with correct loading states', () => {
            expect(logic.values.createdGroupLoading).toBe(false)
            expect(logic.values.createdGroup).toBeNull()
        })
    })

    describe('form validation and submission', () => {
        beforeEach(() => {
            logic = groupsNewLogic({ groupTypeIndex: 0 })
            logic.mount()
        })

        it('prevents submission with validation errors', () => {
            logic.actions.setGroupValue('name', '')
            logic.actions.setGroupValue('group_key', '')

            logic.actions.submitGroup()

            expect(logic.values.groupHasErrors).toBe(true)
        })

        it('accepts valid form data for submission', () => {
            logic.actions.setGroupValue('name', 'Valid Group')
            logic.actions.setGroupValue('group_key', 'valid-group')

            expect(logic.values.groupHasErrors).toBe(false)
            expect(logic.values.group.name).toBe('Valid Group')
            expect(logic.values.group.group_key).toBe('valid-group')
        })
    })

    describe('cleanup and lifecycle', () => {
        it('resets state on unmount', () => {
            logic = groupsNewLogic({ groupTypeIndex: 0 })
            logic.mount()

            logic.actions.setGroupValue('name', 'Test')
            logic.actions.addProperty()

            expect(logic.values.group.name).toBe('Test')
            expect(logic.values.customProperties).toHaveLength(1)

            logic.unmount()
            logic.mount()

            expect(logic.values.createdGroup).toBeNull()
            expect(logic.values.customProperties).toEqual([])
        })

        it('resets custom properties when resetGroup is called', () => {
            logic = groupsNewLogic({ groupTypeIndex: 0 })
            logic.mount()

            logic.actions.setGroupValue('name', 'Test Group')
            logic.actions.addProperty()
            logic.actions.updateProperty(0, 'name', 'test-prop')

            expect(logic.values.customProperties).toHaveLength(1)
            expect(logic.values.customProperties[0].name).toBe('test-prop')

            logic.actions.resetGroup()

            expect(logic.values.customProperties).toEqual([])
            expect(logic.values.createdGroup).toBeNull()
        })
    })

    describe('edge cases and error scenarios', () => {
        beforeEach(() => {
            logic = groupsNewLogic({ groupTypeIndex: 0 })
            logic.mount()
        })

        it('handles special characters in property names and values', () => {
            logic.actions.addProperty()
            logic.actions.updateProperty(0, 'name', 'special-chars!@#$%')
            logic.actions.updateProperty(0, 'value', 'value with spaces & symbols')

            expect(logic.values.customProperties[0]).toEqual({
                name: 'special-chars!@#$%',
                value: 'value with spaces & symbols',
            })
        })

        it('handles unicode characters in form fields', () => {
            logic.actions.setGroupValue('name', 'Group with émojis 🎉')
            logic.actions.setGroupValue('group_key', 'group-key-with-dashes')

            expect(logic.values.group.name).toBe('Group with émojis 🎉')
            expect(logic.values.group.group_key).toBe('group-key-with-dashes')
        })
    })
})

describe('flattenProperties', () => {
    it('filters out empty properties during form submission', () => {
        const rawProperties = [
            { name: '', value: '' },
            { name: '  ', value: '' },
            { name: 'my value is a whitespace', value: ' ' },
            { name: 'empty-value-prop', value: '' },
            { name: 'valid-prop', value: 'valid-value' },
            { name: ' another-valid-prop', value: 'valid-value ' },
        ]

        const flattenedProperties = flattenProperties(rawProperties)

        expect(flattenedProperties).toEqual({ 'valid-prop': 'valid-value', 'another-valid-prop': 'valid-value ' })
    })
})
