import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { useChatActionComposer } from 'products/posthog_ai/frontend/components/ChatActionComposerContext'

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
            }),
        ]),
    }
})

/** The stub's test-only action, absent from the real logic's type. */
const stubActions = (): { setStubContextDisabledReason: (reason: string | undefined) => void } =>
    maxThreadLogic.actions as unknown as { setStubContextDisabledReason: (reason: string | undefined) => void }

function Probe(): JSX.Element {
    const composer = useChatActionComposer()!
    return (
        <>
            <button onClick={() => composer.insert('Send a real test of this workflow to ')}>insert</button>
            <button onClick={() => composer.send('Enable workflow wf_1.')}>send</button>
            <span>{composer.sendDisabledReason ?? 'none'}</span>
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
            question: 'Also rename it\nSend a real test of this workflow to ',
        })
        await expectLogic(maxLogic).toMatchValues({ focusCounter: 1 })
    })

    it.each([
        ['a question in progress', () => maxThreadLogic.actions.setQuestion('wip'), 'Send or clear your draft first'],
        ['a busy thread', () => stubActions().setStubContextDisabledReason('Max is thinking'), 'Max is thinking'],
    ])('reports why send is blocked during %s', async (_case, arrange, reason) => {
        expect(screen.getByText('none')).toBeInTheDocument()
        arrange()
        expect(await screen.findByText(reason)).toBeInTheDocument()
    })
})
