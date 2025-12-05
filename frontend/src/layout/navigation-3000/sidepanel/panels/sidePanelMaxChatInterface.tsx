import { offset } from '@floating-ui/react'
import { useActions, useValues } from 'kea'
import { forwardRef, memo, useEffect, useRef, useState } from 'react'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { ChatMessage, sidePanelMaxAILogic } from './sidePanelMaxAILogic'

const MemoizedMessageContent = memo(function MemoizedMessageContent({ content }: { content: string }) {
    const { openEmailForm } = useActions(supportLogic)

    const processedContent = content
        .replace(new RegExp('<thinking>.*?</thinking>', 's'), '')
        .replace(new RegExp('<search_result_reflection>.*?</search_result_reflection>', 'gs'), '')
        .replace(new RegExp('<search_quality_score>.*?</search_quality_score>', 's'), '')
        .replace(new RegExp('<info_validation>.*?</info_validation>', 's'), '')
        .replace(new RegExp('<url_validation>.*?</url_validation>', 's'), '')
        .replace(new RegExp('<reply>|</reply>', 'g'), '')
        .trim()

    const handleClick = (e: React.MouseEvent<HTMLDivElement>): void => {
        const target = e.target as HTMLElement
        if (target.tagName === 'A' && target.getAttribute('href')?.includes('/support?panel=email')) {
            e.preventDefault()
            openEmailForm()
        }
    }

    return (
        <div onClick={handleClick}>
            <LemonMarkdown disableDocsRedirect>{processedContent}</LemonMarkdown>
        </div>
    )
})

function extractThinkingBlock(content: string): Array<string> {
    const matches = Array.from(content.matchAll(new RegExp('<thinking>(.*?)</thinking>', 'gs')))
    return matches.map((match) => match[1].trim())
}

function extractSearchReflection(content: string): Array<string> {
    const matches = Array.from(
        content.matchAll(new RegExp('<search_result_reflection>(.*?)</search_result_reflection>', 'gs'))
    )
    return matches.map((match) => match[1].trim())
}

function extractSearchQualityScore(content: string): { hasQualityScore: boolean; content: string | null } {
    const qualityMatch = content.match(new RegExp('<search_quality_score>(.*?)</search_quality_score>', 's'))
    if (!qualityMatch) {
        return { hasQualityScore: false, content: null }
    }
    return {
        hasQualityScore: true,
        content: qualityMatch[1].trim(),
    }
}

function extractInfoValidation(content: string): { hasQualityScore: boolean; content: string | null } {
    const qualityMatch = content.match(new RegExp('<info_validation>(.*?)</info_validation>', 's'))
    if (!qualityMatch) {
        return { hasQualityScore: false, content: null }
    }
    return {
        hasQualityScore: true,
        content: qualityMatch[1].trim(),
    }
}

function extractURLValidation(content: string): { hasQualityScore: boolean; content: string | null } {
    const qualityMatch = content.match(new RegExp('<url_validation>(.*?)</url_validation>', 's'))
    if (!qualityMatch) {
        return { hasQualityScore: false, content: null }
    }
    return {
        hasQualityScore: true,
        content: qualityMatch[1].trim(),
    }
}

const MaxChatInterfaceContent = forwardRef<HTMLDivElement, Record<string, never>>(
    function MaxChatInterfaceContent(_, ref) {
        const { currentMessages, isSearchingThinking, isRateLimited, hasServerError } = useValues(sidePanelMaxAILogic)
        const { submitMessage } = useActions(sidePanelMaxAILogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)
        const [inputMessage, setInputMessage] = useState('')

        useEffect(() => {
            if (dataProcessingAccepted) {
                submitMessage('__GREETING__')
            }
        }, [submitMessage, dataProcessingAccepted])

        const showInput = currentMessages.length > 0 && currentMessages.some((msg) => msg.role === 'assistant')

        const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                if (inputMessage.trim() && !isSearchingThinking && dataProcessingAccepted) {
                    submitMessage(inputMessage)
                    setInputMessage('')
                }
            }
        }

        const messagesEndRef = useRef<HTMLDivElement>(null)
        const endButtonRef = useRef<HTMLDivElement>(null)
        const prevMessageCountRef = useRef(currentMessages.length)

        useEffect(() => {
            if (prevMessageCountRef.current !== currentMessages.length) {
                setTimeout(() => {
                    endButtonRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
                }, 100)
                prevMessageCountRef.current = currentMessages.length
            }
        }, [currentMessages])

        const displayMessages = currentMessages.filter((message) => message.content !== '__GREETING__')

        return (
            <div ref={ref} className="flex flex-col h-full">
                <div className="flex-1 overflow-y-auto p-3 deprecated-space-y-4 [overflow-anchor:none]">
                    <div className="bg-surface-primary dark:bg-transparent rounded p-1">
                        <h4 className="mb-2">Tips for using PostHog AI through chat:</h4>
                        <ul className="list-disc pl-4 deprecated-space-y-2 text-secondary">
                            <li>PostHog AI can't handle files or images (yet.)</li>
                            <li>Replies can take up to 3 mins due to rate-limiting.</li>
                            <li>PostHog AI can make mistakes. Please double-check responses.</li>
                        </ul>
                    </div>

                    {displayMessages.length === 0 ? (
                        <div className="flex items-center gap-2 text-secondary">
                            <span>PostHog AI is thinking...</span>
                            <Spinner className="text-lg" />
                        </div>
                    ) : (
                        displayMessages.map(
                            (message: ChatMessage, idx: number): JSX.Element => (
                                <div
                                    key={`${message.timestamp}-${idx}`}
                                    className={`flex w-full ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                                >
                                    {message.role === 'user' && (
                                        <div className="text-sm text-secondary mr-2 mt-2">You</div>
                                    )}

                                    <div
                                        className={`${message.role === 'assistant' ? 'flex flex-col' : ''} max-w-full`}
                                    >
                                        {message.role === 'assistant' && (
                                            <div className="text-sm text-primary-alt mb-1">Max</div>
                                        )}
                                        <div
                                            className={`p-2 rounded-lg min-w-[90%] whitespace-pre-wrap ${
                                                message.role === 'assistant'
                                                    ? 'bg-surface-primary dark:bg-surface-primary text-default'
                                                    : 'bg-surface-primary dark:bg-surface-secondary text-default'
                                            }`}
                                        >
                                            {message.role === 'assistant'
                                                ? typeof message.content === 'string' &&
                                                  (message.content.includes('<search_state>started</search_state>') ? (
                                                      <div className="flex items-center gap-2">
                                                          <span>Max is searching...</span>
                                                          <Spinner className="text-lg" />
                                                      </div>
                                                  ) : message.content.includes(
                                                        '<search_state>completed</search_state>'
                                                    ) ? (
                                                      <div>Max searched</div>
                                                  ) : (
                                                      <>
                                                          <MemoizedMessageContent content={message.content} />

                                                          {/* Only show analysis for non-greeting messages */}
                                                          {idx === 0
                                                              ? null
                                                              : (extractThinkingBlock(message.content).length > 0 ||
                                                                    extractSearchReflection(message.content).length >
                                                                        0 ||
                                                                    extractSearchQualityScore(message.content)
                                                                        .hasQualityScore ||
                                                                    extractInfoValidation(message.content)
                                                                        .hasQualityScore ||
                                                                    extractURLValidation(message.content)
                                                                        .hasQualityScore) && (
                                                                    <LemonCollapse
                                                                        key={`analysis-${message.timestamp}`}
                                                                        className="mt-4 text-sm"
                                                                        panels={[
                                                                            {
                                                                                key: 'analysis',
                                                                                header: (
                                                                                    <span className="text-secondary">
                                                                                        What was PostHog AI thinking?
                                                                                    </span>
                                                                                ),
                                                                                content: (
                                                                                    <div className="deprecated-space-y-3 p-1">
                                                                                        {/* Thinking blocks */}
                                                                                        {extractThinkingBlock(
                                                                                            message.content
                                                                                        ).map((content, index) => (
                                                                                            <LemonCollapse
                                                                                                key={`thinking-${index}-${message.timestamp}`}
                                                                                                panels={[
                                                                                                    {
                                                                                                        key: 'thinking',
                                                                                                        header: 'Thinking',
                                                                                                        content: (
                                                                                                            <div>
                                                                                                                {
                                                                                                                    content
                                                                                                                }
                                                                                                            </div>
                                                                                                        ),
                                                                                                    },
                                                                                                ]}
                                                                                            />
                                                                                        ))}

                                                                                        {/* Search Reflection blocks */}
                                                                                        {extractSearchReflection(
                                                                                            message.content
                                                                                        ).map((content, index) => (
                                                                                            <LemonCollapse
                                                                                                key={`reflection-${index}-${message.timestamp}`}
                                                                                                panels={[
                                                                                                    {
                                                                                                        key: 'reflection',
                                                                                                        header: 'Search Reflection',
                                                                                                        content: (
                                                                                                            <div>
                                                                                                                {
                                                                                                                    content
                                                                                                                }
                                                                                                            </div>
                                                                                                        ),
                                                                                                    },
                                                                                                ]}
                                                                                            />
                                                                                        ))}

                                                                                        {/* Search Quality Score */}
                                                                                        {extractSearchQualityScore(
                                                                                            message.content
                                                                                        ).hasQualityScore && (
                                                                                            <LemonCollapse
                                                                                                panels={[
                                                                                                    {
                                                                                                        key: 'quality',
                                                                                                        header: 'Search Quality',
                                                                                                        content: (
                                                                                                            <div>
                                                                                                                {
                                                                                                                    extractSearchQualityScore(
                                                                                                                        message.content
                                                                                                                    )
                                                                                                                        .content
                                                                                                                }
                                                                                                            </div>
                                                                                                        ),
                                                                                                    },
                                                                                                ]}
                                                                                            />
                                                                                        )}

                                                                                        {/* Info Validation */}
                                                                                        {extractInfoValidation(
                                                                                            message.content
                                                                                        ).hasQualityScore && (
                                                                                            <LemonCollapse
                                                                                                panels={[
                                                                                                    {
                                                                                                        key: 'info',
                                                                                                        header: 'Information Validation',
                                                                                                        content: (
                                                                                                            <div>
                                                                                                                {
                                                                                                                    extractInfoValidation(
                                                                                                                        message.content
                                                                                                                    )
                                                                                                                        .content
                                                                                                                }
                                                                                                            </div>
                                                                                                        ),
                                                                                                    },
                                                                                                ]}
                                                                                            />
                                                                                        )}

                                                                                        {/* URL Validation */}
                                                                                        {extractURLValidation(
                                                                                            message.content
                                                                                        ).hasQualityScore && (
                                                                                            <LemonCollapse
                                                                                                panels={[
                                                                                                    {
                                                                                                        key: 'url',
                                                                                                        header: 'URL Validation',
                                                                                                        content: (
                                                                                                            <div>
                                                                                                                {
                                                                                                                    extractURLValidation(
                                                                                                                        message.content
                                                                                                                    )
                                                                                                                        .content
                                                                                                                }
                                                                                                            </div>
                                                                                                        ),
                                                                                                    },
                                                                                                ]}
                                                                                            />
                                                                                        )}
                                                                                    </div>
                                                                                ),
                                                                            },
                                                                        ]}
                                                                    />
                                                                )}
                                                      </>
                                                  ))
                                                : message.content}
                                        </div>
                                    </div>
                                </div>
                            )
                        )
                    )}
                    {(hasServerError || isRateLimited) && (
                        <div className="flex justify-start">
                            <div className="flex flex-col">
                                <div className="text-sm text-primary-alt mb-1">Max</div>
                                <div className="p-2 rounded-lg bg-surface-primary dark:bg-surface-primary text-default">
                                    <div className="flex items-center gap-2">
                                        <span>
                                            {hasServerError
                                                ? "🫣 Uh-oh. I wasn't able to connect to the Anthropic API (my brain!) Please try sending your message again in about 1 minute? (If you see this message twice in a row, please use the 'End chat' button below to start a new chat.)"
                                                : isRateLimited
                                                  ? "🫣 Uh-oh, I'm really popular today, we've been rate-limited. I just need to catch my breath. Hang on, I'll repeat your question and resume searching in less than a minute. If I repeat it more than 3 times, maybe try again later."
                                                  : 'Searching and thinking...'}
                                        </span>
                                        <Spinner className="text-lg" />
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    <div ref={messagesEndRef} />
                </div>

                <LemonDivider />

                {showInput && (
                    <>
                        {isSearchingThinking && (
                            <div className="flex items-center gap-2 p-2 text-secondary justify-center">
                                <span>Max is searching and thinking...</span>
                                <Spinner className="text-sm" />
                            </div>
                        )}
                        <form className="p-4 pb-1">
                            <LemonTextArea
                                value={inputMessage}
                                onChange={setInputMessage}
                                onKeyDown={handleKeyDown}
                                placeholder="Type or paste here..."
                                minRows={4}
                                maxRows={12}
                                className="w-full"
                                data-attr="max-chat-input"
                            />
                            <div className="px-0 text-xs text-secondary mt-1 mb-2">
                                `enter` to send, `shift+enter` for a new line
                            </div>
                            <LemonButton
                                type="primary"
                                data-attr="max-chat-send"
                                fullWidth
                                center
                                className={isSearchingThinking ? 'opacity-50' : ''}
                                onClick={(e) => {
                                    e.preventDefault()
                                    if (inputMessage.trim() && !isSearchingThinking && dataProcessingAccepted) {
                                        submitMessage(inputMessage)
                                        setInputMessage('')
                                    }
                                }}
                            >
                                Send
                            </LemonButton>
                        </form>
                        <div ref={endButtonRef} />
                    </>
                )}
            </div>
        )
    }
)

export function MaxChatInterface(): JSX.Element {
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    return (
        <div className="relative">
            {dataProcessingAccepted ? (
                <MaxChatInterfaceContent />
            ) : (
                <AIConsentPopoverWrapper placement="right-start" middleware={[offset(-12)]} showArrow>
                    <MaxChatInterfaceContent />
                </AIConsentPopoverWrapper>
            )}
        </div>
    )
}
