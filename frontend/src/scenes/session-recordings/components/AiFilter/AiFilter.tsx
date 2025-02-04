/**
 * @fileoverview A component that allows user to "chat with recordings" using Max AI
 */
import { IconAIText, IconPerson, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput, LemonTag } from '@posthog/lemon-ui'
import { BuiltLogic, useActions, useValues } from 'kea'
import { sessionRecordingsPlaylistLogicType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogicType'

import { aiFilterLogic } from './aiFilterLogic'

export function AiFilter({ logic }: { logic: BuiltLogic<sessionRecordingsPlaylistLogicType> }): JSX.Element {
    const { setFilters, resetFilters } = useActions(logic)
    const filterLogic = aiFilterLogic({ setFilters, resetFilters })
    const { messages, input, isLoading } = useValues(filterLogic)
    const { setInput, handleReset, handleSend } = useActions(filterLogic)

    return (
        <>
            <LemonCollapse
                className="mb-2"
                panels={[
                    {
                        key: 'chat-with-recordings',
                        header: (
                            <div className="no-flex py-2">
                                <h3 className="mb-0 flex items-center gap-1">
                                    Chat with your recording list <LemonTag type="completion">ALPHA</LemonTag>
                                </h3>
                                <div className="text-xs font-normal text-muted-alt">
                                    Ask Max AI to find recordings matching your needs - like "show me recordings with
                                    rage clicks" or "find recordings where users visited pricing"
                                </div>
                            </div>
                        ),
                        content: (
                            <>
                                <div className="gap-2">
                                    <div>
                                        {messages.length > 1 && (
                                            <div className="max-w-96 ">
                                                {messages
                                                    .filter((message) => message.role !== 'system')
                                                    .map((message, index) => (
                                                        <div
                                                            key={index}
                                                            className="border rounded border-gray-200 p-2 bg-white my-2"
                                                        >
                                                            {message.role === 'user' ? (
                                                                <>
                                                                    <strong>
                                                                        <IconPerson />
                                                                        You:
                                                                    </strong>{' '}
                                                                    {message.content}
                                                                </>
                                                            ) : (
                                                                <>
                                                                    <strong>
                                                                        <IconAIText />
                                                                        Max AI:
                                                                    </strong>{' '}
                                                                    {message.content}
                                                                </>
                                                            )}
                                                        </div>
                                                    ))}
                                            </div>
                                        )}
                                        {messages.length > 1 && (
                                            <div>
                                                <LemonButton
                                                    icon={<IconTrash />}
                                                    onClick={handleReset}
                                                    disabled={isLoading}
                                                    type="tertiary"
                                                    size="xsmall"
                                                >
                                                    Reset
                                                </LemonButton>
                                            </div>
                                        )}
                                        <div className="flex items-center gap-x-2">
                                            <div>
                                                <LemonInput
                                                    value={input}
                                                    onChange={(value) => setInput(value)}
                                                    placeholder="Show me recordings of people who ..."
                                                    className="my-2 w-96"
                                                />
                                            </div>
                                            <div>
                                                <LemonButton
                                                    onClick={handleSend}
                                                    disabled={isLoading || input.length === 0}
                                                    loading={isLoading}
                                                    type="primary"
                                                    size="small"
                                                >
                                                    {isLoading ? '' : 'Send'}
                                                </LemonButton>
                                            </div>
                                        </div>
                                    </div>
                                    {messages.length === 1 && (
                                        <div>
                                            <strong className="text-sm">People usually ask Max AI:</strong>
                                            <LemonButton
                                                className="mb-1"
                                                type="secondary"
                                                onClick={() =>
                                                    setInput(
                                                        'Show me recordings of people who visited sign up page in the last 24 hours'
                                                    )
                                                }
                                            >
                                                <span className="font-normal text-sx italic">
                                                    Show me recordings of people who visited sign up page in the last 24
                                                    hours
                                                </span>
                                            </LemonButton>
                                            <LemonButton
                                                className="mb-1"
                                                type="secondary"
                                                onClick={() =>
                                                    setInput('Show me recordings of people who are frustarated')
                                                }
                                            >
                                                <span className="font-normal text-sx italic">
                                                    Show me recordings of people who are frustarated
                                                </span>
                                            </LemonButton>
                                            <LemonButton
                                                type="secondary"
                                                onClick={() => setInput('Show me recordings of people who facing bugs')}
                                            >
                                                <span className="font-normal text-sx italic">
                                                    Show me recordings of people who facing bugs
                                                </span>
                                            </LemonButton>
                                        </div>
                                    )}
                                </div>
                            </>
                        ),
                    },
                ]}
            />
        </>
    )
}
