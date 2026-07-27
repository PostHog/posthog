import { MOCK_DEFAULT_BASIC_USER, MOCK_SECOND_BASIC_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, render } from '@testing-library/react'
import { Editor } from '@tiptap/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'
import { createRef } from 'react'

import { membersLogic } from 'scenes/organization/membersLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Mentions } from './MentionsExtension'

type MentionsHandle = { onKeyDown: (event: KeyboardEvent) => boolean }

const mockMembers = [
    {
        id: '1',
        user: MOCK_DEFAULT_BASIC_USER,
        level: 8,
        joined_at: '2020-09-24T15:05:26.758796Z',
        updated_at: '2020-09-24T15:05:26.758837Z',
        is_2fa_enabled: false,
        has_social_auth: false,
        last_login: '2020-09-24T15:05:26.758796Z',
    },
    {
        id: '2',
        user: MOCK_SECOND_BASIC_USER,
        level: 1,
        joined_at: '2021-03-11T19:11:11Z',
        updated_at: '2021-03-11T19:11:11Z',
        is_2fa_enabled: false,
        has_social_auth: false,
        last_login: '2021-03-11T19:11:11Z',
    },
]

function createMockEditor(): { editor: Editor; run: jest.Mock; insertContentAt: jest.Mock } {
    const run = jest.fn()
    const insertContentAt = jest.fn(() => ({ run }))
    const deleteRange = jest.fn(() => ({ insertContentAt }))
    const focus = jest.fn(() => ({ deleteRange }))
    const chain = jest.fn(() => ({ focus }))
    return { editor: { chain } as unknown as Editor, run, insertContentAt }
}

function renderMentions(editor: Editor, onClose: () => void): React.RefObject<MentionsHandle> {
    const ref = createRef<MentionsHandle>()
    render(
        <Provider>
            <Mentions
                ref={ref as React.Ref<any>}
                editor={editor}
                range={{ from: 0, to: 1 }}
                query=""
                onClose={onClose}
            />
        </Provider>
    )
    return ref
}

describe('Mentions', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/members/': { results: mockMembers },
            },
        })
        initKeaTests()
    })

    it('does not swallow Enter when there is no matching member', () => {
        // members never loaded -> meFirstMembers is empty -> no selectable member
        const { editor, run } = createMockEditor()
        const onClose = jest.fn()

        const ref = renderMentions(editor, onClose)
        const handled = ref.current?.onKeyDown(new KeyboardEvent('keydown', { key: 'Enter' }))

        expect(handled).toBe(false)
        expect(editor.chain).not.toHaveBeenCalled()
        expect(run).not.toHaveBeenCalled()
        expect(onClose).not.toHaveBeenCalled()
    })

    it('inserts the selected member and closes on Enter when a match exists', async () => {
        await expectLogic(membersLogic, () => {
            membersLogic.mount()
            membersLogic.actions.loadAllMembers()
        }).toDispatchActions(['loadAllMembersSuccess'])

        const { editor, run, insertContentAt } = createMockEditor()
        const onClose = jest.fn()

        const ref = renderMentions(editor, onClose)
        const handled = ref.current?.onKeyDown(new KeyboardEvent('keydown', { key: 'Enter' }))

        expect(handled).toBe(true)
        expect(editor.chain).toHaveBeenCalledTimes(1)
        expect(run).toHaveBeenCalledTimes(1)
        expect(insertContentAt).toHaveBeenCalledWith(0, [
            expect.objectContaining({ attrs: { id: membersLogic.values.meFirstMembers[0].user.id } }),
        ])
        expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('wraps selection around with ArrowUp/ArrowDown', async () => {
        await expectLogic(membersLogic, () => {
            membersLogic.mount()
            membersLogic.actions.loadAllMembers()
        }).toDispatchActions(['loadAllMembersSuccess'])

        const members = membersLogic.values.meFirstMembers
        expect(members.length).toBe(mockMembers.length)

        const { editor, insertContentAt } = createMockEditor()
        const onClose = jest.fn()
        const ref = renderMentions(editor, onClose)

        // ArrowUp from the first item wraps to the last.
        act(() => {
            ref.current?.onKeyDown(new KeyboardEvent('keydown', { key: 'ArrowUp' }))
        })
        act(() => {
            ref.current?.onKeyDown(new KeyboardEvent('keydown', { key: 'Enter' }))
        })
        expect(insertContentAt).toHaveBeenLastCalledWith(0, [
            expect.objectContaining({ attrs: { id: members[members.length - 1].user.id } }),
        ])

        // From the last item, ArrowDown wraps back to the first.
        act(() => {
            ref.current?.onKeyDown(new KeyboardEvent('keydown', { key: 'ArrowDown' }))
        })
        act(() => {
            ref.current?.onKeyDown(new KeyboardEvent('keydown', { key: 'Enter' }))
        })
        expect(insertContentAt).toHaveBeenLastCalledWith(0, [
            expect.objectContaining({ attrs: { id: members[0].user.id } }),
        ])
    })

    it.each(['ArrowUp', 'ArrowDown'])('%s is handled even when the list is empty', (key) => {
        const { editor } = createMockEditor()
        const ref = renderMentions(editor, jest.fn())

        expect(ref.current?.onKeyDown(new KeyboardEvent('keydown', { key }))).toBe(true)
        expect(editor.chain).not.toHaveBeenCalled()
    })
})
