import { expectLogic } from 'kea-test-utils'

import { ObjectTagsLogicProps, objectTagsLogic } from 'lib/components/ObjectTags/objectTagsLogic'

import { initKeaTests } from '~/test/init'

describe('objectTagsLogic', () => {
    let logic: ReturnType<typeof objectTagsLogic.build>
    let props: ObjectTagsLogicProps

    beforeEach(() => {
        initKeaTests()
        props = {
            id: 1,
            onChange: jest.fn(),
        }
        logic = objectTagsLogic(props)
        logic.actions.setTags(['a', 'b', 'c'])
        logic.mount()
    })

    describe('local tags state', () => {
        it('initialization', async () => {
            await expectLogic(logic).toMatchValues({
                editingTags: false,
            })
        })
        it('cleans new tags', async () => {
            await expectLogic(logic, async () => {
                logic.actions.setEditingTags(true)
                logic.actions.setTags(['a', 'b', 'c', 'Nightly'])
            }).toMatchValues({
                editingTags: true,
            })
            // @ts-expect-error
            const mockedOnChange = props.onChange?.mock
            expect(mockedOnChange.calls.length).toBe(1)
            expect(mockedOnChange.calls[0][0]).toEqual(['a', 'b', 'c', 'nightly'])
        })
        it('removes duplicate tags', async () => {
            await expectLogic(logic, async () => {
                logic.actions.setTags(['a', 'nightly', 'b', 'c', 'nightly'])
            })
            // @ts-expect-error
            const mockedOnChange = props.onChange?.mock
            expect(mockedOnChange.calls.length).toBe(1)
            expect(mockedOnChange.calls[0][0]).toEqual(['a', 'nightly', 'b', 'c'])
        })
    })
})
