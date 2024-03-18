import { expectLogic } from 'kea-test-utils'
import { objectTagsLogic, ObjectTagsLogicProps } from 'lib/components/ObjectTags/objectTagsLogic'

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
        it('handle adding a new tag', async () => {
            await expectLogic(logic, async () => {
                logic.actions.setEditingTags(true)
                logic.actions.setTags(['a', 'b', 'c', 'Nightly'])
            })
                .toDispatchActions([logic.actionCreators.setTags(['a', 'b', 'c', 'nightly'])])
                .toMatchValues({
                    editingTags: true,
                })
            // @ts-expect-error
            const mockedOnChange = props.onChange?.mock
            expect(mockedOnChange.calls.length).toBe(1)
            expect(mockedOnChange.calls[0]).toEqual(['a', 'b', 'c', 'nightly'])
        })
        // it('noop on duplicate tag', async () => {
        //     await expectLogic(logic, async () => {
        //         logic.actions.handleAdd('a')
        //     })
        //         .toDispatchActions(['handleAdd'])
        //         .toNotHaveDispatchedActions(['setTags'])
        //         .toMatchValues({
        //             tags: ['a', 'b', 'c'],
        //         })
        //     // @ts-expect-error
        //     expect(props.onChange?.mock.calls.length).toBe(0)
        // })
    })
})
