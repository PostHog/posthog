import './ToolbarAIMenu.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconAI, IconSend, IconStopFilled, IconWarning } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'

import { ToolbarMessage, toolbarAILogic } from './toolbarAILogic'

function MessageBubble({ message }: { message: ToolbarMessage }): JSX.Element {
    const isUser = message.role === 'user'
    return (
        <div className={clsx('ToolbarAIMenu__message', isUser && 'ToolbarAIMenu__message--user')}>
            <div className="ToolbarAIMenu__message-role">{isUser ? 'You' : 'Max'}</div>
            <div className={clsx('ToolbarAIMenu__message-content', message.error && 'text-danger')}>
                {message.content || (message.streaming ? <Spinner /> : null)}
            </div>
        </div>
    )
}

export function ToolbarAIMenu(): JSX.Element {
    const { messages, isStreaming, isCapturingContext, isBusy, error } = useValues(toolbarAILogic)
    const { submitMessage, cancelStream, reset } = useActions(toolbarAILogic)

    const [draft, setDraft] = useState('')
    const scrollRef = useRef<HTMLDivElement | null>(null)
    const inputRef = useRef<HTMLTextAreaElement | null>(null)

    // Auto-scroll to bottom when new content arrives.
    useEffect(() => {
        const el = scrollRef.current
        if (el) {
            el.scrollTop = el.scrollHeight
        }
    }, [messages])

    // Refocus the input after a turn completes so users can type the next question
    // without clicking back into the textarea.
    useEffect(() => {
        if (!isBusy) {
            inputRef.current?.focus()
        }
    }, [isBusy])

    const onSubmit = (): void => {
        if (!draft.trim() || isBusy) {
            return
        }
        submitMessage(draft)
        setDraft('')
    }

    const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            onSubmit()
        }
    }

    return (
        <ToolbarMenu className="ToolbarAIMenu">
            <ToolbarMenu.Header>
                <div className="flex items-center justify-between w-full pr-2">
                    <div className="flex items-center gap-1 font-semibold">
                        <IconAI className="text-lg" />
                        <span>Max AI</span>
                    </div>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={reset}
                        disabledReason={isBusy ? 'Wait for the current response to finish' : undefined}
                    >
                        New chat
                    </LemonButton>
                </div>
            </ToolbarMenu.Header>

            <ToolbarMenu.Body className="ToolbarAIMenu__body">
                <div ref={scrollRef} className="ToolbarAIMenu__scroll">
                    {messages.length === 0 ? (
                        <div className="ToolbarAIMenu__empty">
                            <IconAI className="text-3xl mb-2" />
                            <div className="font-semibold">Ask Max about this page</div>
                            <div className="text-xs text-secondary mt-1">
                                Max can see your page and your PostHog data. Try: "Why is the signup button click rate
                                dropping?"
                            </div>
                        </div>
                    ) : (
                        messages.map((m) => <MessageBubble key={m.id} message={m} />)
                    )}
                    {isCapturingContext ? (
                        <div className="ToolbarAIMenu__status">
                            <Spinner /> Capturing page context…
                        </div>
                    ) : null}
                    {error ? (
                        <div className="ToolbarAIMenu__status text-danger">
                            <IconWarning /> {error}
                        </div>
                    ) : null}
                </div>
            </ToolbarMenu.Body>

            <ToolbarMenu.Footer className="ToolbarAIMenu__footer">
                <div className="flex flex-col gap-1 w-full">
                    <div className="text-xs text-secondary">📷 Page screenshot and DOM snapshot will be attached</div>
                    <div className="flex items-end gap-2 w-full">
                        <textarea
                            ref={inputRef}
                            className="ToolbarAIMenu__input"
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            onKeyDown={onKeyDown}
                            placeholder="Ask Max…"
                            rows={1}
                            disabled={isBusy}
                        />
                        {isStreaming ? (
                            <LemonButton
                                size="small"
                                type="secondary"
                                icon={<IconStopFilled />}
                                onClick={cancelStream}
                                tooltip="Stop generation"
                            />
                        ) : (
                            <LemonButton
                                size="small"
                                type="primary"
                                icon={<IconSend />}
                                onClick={onSubmit}
                                disabledReason={
                                    isBusy ? 'Wait for Max to finish' : !draft.trim() ? 'Type a message' : undefined
                                }
                            />
                        )}
                    </div>
                </div>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}
