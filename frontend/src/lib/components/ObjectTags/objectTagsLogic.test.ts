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
            tags: ['a', 'b', 'c'],
        }
        logic = objectTagsLogic(props)
        logic.mount()
    })

    describe('local tags state', () => {
        it('initialization', async () => {
            await expectLogic(logic).toMatchValues({
                tags: ['a', 'b', 'c'],
                addingNewTag: false,
                newTag: '',
                deletedTags: [],
            })
        })
        it('handle adding a new tag', async () => {
            await expectLogic(logic, async () => {
                logic.actions.setNewTag('Nigh')
                logic.actions.handleAdd('Nightly')
            })
                .toDispatchActions(['setNewTag'])
                .toMatchValues({
                    newTag: 'Nigh',
                    cleanedNewTag: 'nigh', //user only needs to type part of the tag to find it in a list
                })
                .toDispatchActions(['handleAdd', logic.actionCreators.setTags(['a', 'b', 'c', 'nightly'])])
                .toMatchValues({
                    tags: ['a', 'b', 'c', 'nightly'],
                    addingNewTag: false,
                    newTag: '',
                })
            // @ts-expect-error
            const mockedOnChange = props.onChange?.mock
            expect(mockedOnChange.calls.length).toBe(1)
            expect(mockedOnChange.calls[0][0]).toBe('nightly')
            expect(mockedOnChange.calls[0][1]).toEqual(['a', 'b', 'c', 'nightly'])
        })
        it('noop on duplicate tag', async () => {
            await expectLogic(logic, async () => {
                logic.actions.handleAdd('a')
            })
                .toDispatchActions(['handleAdd'])
                .toNotHaveDispatchedActions(['setTags'])
                .toMatchValues({
                    tags: ['a', 'b', 'c'],
                })
            // @ts-expect-error
            expect(props.onChange?.mock.calls.length).toBe(0)
        })
        it('handle deleting a tag', async () => {
            await expectLogic(logic, async () => {
                logic.actions.handleDelete('a')
            })
                .toDispatchActions(['handleDelete', logic.actionCreators.setTags(['b', 'c'])])
                .toMatchValues({
                    tags: ['b', 'c'],
                })
            // @ts-expect-error
            const mockedOnChange = props.onChange?.mock
            expect(mockedOnChange.calls.length).toBe(1)
            expect(mockedOnChange.calls[0][0]).toBe('a')
            expect(mockedOnChange.calls[0][1]).toEqual(['b', 'c'])
        })
    })
})
