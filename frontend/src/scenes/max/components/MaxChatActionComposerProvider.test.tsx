import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { useChatActionComposer } from 'products/posthog_ai/frontend/api/primitives'

import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { MaxChatActionComposerProvider } from './MaxChatActionComposerProvider'

// Both Max logics are reduced to the input state and actions the provider touches.
jest.mock('../maxLogic', () => {
    const { kea, actions, path, reducers } = jest.requireActual('kea')
    return {
        maxLogic: kea([
            path(['test', 'maxLogicStub']),
            actions({ focusInput: true }),
            reducers({ focusCounter: [0, { focusInput: (state: number) => state + 1 }] }),
        ]),
    }
})
jest.mock('../maxThreadLogic', () => {
    const { kea, actions, path, reducers } = jest.requireActual('kea')
    return {
        maxThreadLogic: kea([
            path(['test', 'maxThreadLogicStub']),
            actions({
                askMax: (prompt: string | null) => ({ prompt }),
                setQuestion: (question: string) => ({ question }),
                setStubContextDisabledReason: (reason: string | undefined) => ({ reason }),
                setStubShared: (shared: boolean) => ({ shared }),
                setStubPendingRequest: (pending: boolean) => ({ pending }),
            }),
            reducers({
                question: ['', { setQuestion: (_: string, { question }: { question: string }) => question }],
                contextDisabledReason: [
                    undefined as string | undefined,
                    {
                        setStubContextDisabledReason: (_: unknown, { reason }: { reason: string | undefined }) =>
                            reason,
                    },
                ],
                queueDisabledReason: [undefined as string | undefined, {}],
                pendingSandboxPermissionRequest: [
                    null as unknown,
                    {
                        setStubPendingRequest: (_: unknown, { pending }: { pending: boolean }) =>
                            pending ? { requestId: 'req-1' } : null,
                    },
                ],
                isSharedThread: [false, { setStubShared: (_: boolean, { shared }: { shared: boolean }) => shared }],
            }),
        ]),
    }
})

interface StubActions {
    setStubContextDisabledReason: (reason: string | undefined) => void
    setStubShared: (shared: boolean) => void
    setStubPendingRequest: (pending: boolean) => void
}

/** The stub's test-only actions, absent from the real logic's type. */
const stubActions = (): StubActions => maxThreadLogic.actions as unknown as StubActions

function Probe(): JSX.Element {
    const composer = useChatActionComposer()
    if (!composer) {
        return <span>no composer</span>
    }
    return (
        <>
            <button onClick={() => composer.insert('Send a test email of this workflow to ')}>insert</button>
            <button onClick={() => composer.send('Enable workflow wf_1.')}>send</button>
            <span>{composer.sendDisabledReason ?? 'none'}</span>
            <span>insert: {composer.insertDisabledReason ?? 'live'}</span>
        </>
    )
}

describe('MaxChatActionComposerProvider', () => {
    beforeEach(() => {
        initKeaTests()
        maxLogic.mount()
        maxThreadLogic.mount()
        render(
            <MaxChatActionComposerProvider>
                <Probe />
            </MaxChatActionComposerProvider>
        )
    })
    afterEach(cleanup)

    it('send asks Max with the message, so a run click in the side panel starts the next turn', async () => {
        fireEvent.click(screen.getByText('send'))
        await expectLogic(maxThreadLogic).toDispatchActions([
            maxThreadLogic.actionCreators.askMax('Enable workflow wf_1.'),
        ])
    })

    it('insert appends to the question and focuses the input', async () => {
        maxThreadLogic.actions.setQuestion('Also rename it')
        fireEvent.click(screen.getByText('insert'))
        await expectLogic(maxThreadLogic).toMatchValues({
            question: 'Also rename it\nSend a test email of this workflow to ',
        })
        await expectLogic(maxLogic).toMatchValues({ focusCounter: 1 })
    })

    it.each([
        ['a question in progress', () => maxThreadLogic.actions.setQuestion('wip'), 'Send or clear your draft first'],
        [
            'an impersonated session',
            () =>
                stubActions().setStubContextDisabledReason('You should create new conversations during impersonation.'),
            'You should create new conversations during impersonation.',
        ],
    ])('reports why send is blocked during %s', async (_case, arrange, reason) => {
        expect(screen.getByText('none')).toBeInTheDocument()
        arrange()
        expect(await screen.findByText(reason)).toBeInTheDocument()
    })

    it('blocks insert while a pending request takes the place of the input', async () => {
        expect(screen.getByText('insert: live')).toBeInTheDocument()
        stubActions().setStubPendingRequest(true)
        expect(await screen.findByText('insert: Answer the request below first')).toBeInTheDocument()
    })

    // Another user's conversation has no input, so its buttons must not write into one.
    it('gives a shared thread no composer', async () => {
        stubActions().setStubShared(true)
        expect(await screen.findByText('no composer')).toBeInTheDocument()
    })
})
