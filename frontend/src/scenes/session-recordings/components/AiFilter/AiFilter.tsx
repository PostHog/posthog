/**
 * @fileoverview A component that allows user to "chat with recordings" using Max AI
 */
import { IconAIText, IconPerson, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput, LemonTag, Popover } from '@posthog/lemon-ui'
import { BuiltLogic, useActions, useValues } from 'kea'
import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { sessionRecordingsPlaylistLogicType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogicType'

import { aiFilterLogic } from './aiFilterLogic'

export function AiFilter({ logic }: { logic: BuiltLogic<sessionRecordingsPlaylistLogicType> }): JSX.Element {
    const { setFilters, resetFilters } = useActions(logic)
    const filterLogic = aiFilterLogic({ setFilters, resetFilters })
    const { messages, input, isLoading } = useValues(filterLogic)
    const { setInput, handleReset, handleSend } = useActions(filterLogic)
    const { acceptDataProcessing } = useActions(maxGlobalLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)

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
                                <div className="gap-2 justify-center flex flex-col">
                                    <div>
                                        {messages.length > 0 && (
                                            <div className="max-w-1/2 min-w-96">
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
                                                                    <strong className="text-primary">
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
                                        {messages.length > 0 && (
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
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter') {
                                                            handleSend()
                                                        }
                                                    }}
                                                />
                                            </div>
                                            <div>
                                                <LemonButton
                                                    onClick={handleSend}
                                                    disabled={
                                                        isLoading || input.length === 0 || !dataProcessingAccepted
                                                    }
                                                    loading={isLoading}
                                                    type="primary"
                                                    size="small"
                                                >
                                                    {isLoading ? '' : 'Send'}
                                                </LemonButton>
                                            </div>
                                            {!dataProcessingAccepted && (
                                                <div className="flex justify-center">
                                                    <Popover
                                                        overlay={
                                                            <div className="m-1.5">
                                                                <p className="font-medium text-pretty mb-1.5">
                                                                    Hi! I use OpenAI services to analyze your data,
                                                                    <br />
                                                                    so that you can focus on building. This <em>
                                                                        can
                                                                    </em>{' '}
                                                                    include
                                                                    <br />
                                                                    personal data of your users, if you're capturing it.
                                                                    <br />
                                                                    <em>
                                                                        Your data won't be used for training models.
                                                                    </em>
                                                                </p>
                                                                <LemonButton
                                                                    type="secondary"
                                                                    size="small"
                                                                    onClick={() => acceptDataProcessing()}
                                                                >
                                                                    Got it, I accept OpenAI processing data
                                                                </LemonButton>
                                                            </div>
                                                        }
                                                        placement="right-end"
                                                        showArrow
                                                        visible={true}
                                                    >
                                                        <HedgehogBuddy
                                                            static
                                                            hedgehogConfig={{
                                                                ...hedgehogConfig,
                                                                walking_enabled: false,
                                                                controls_enabled: false,
                                                            }}
                                                            onClick={(actor) => {
                                                                if (Math.random() < 0.01) {
                                                                    actor.setOnFire()
                                                                } else {
                                                                    actor.setRandomAnimation()
                                                                }
                                                            }}
                                                            onActorLoaded={(actor) =>
                                                                setTimeout(() => {
                                                                    actor.setAnimation('wave')
                                                                    // Always start out facing right so that the data processing popover is more readable
                                                                    actor.direction = 'right'
                                                                }, 100)
                                                            }
                                                        />
                                                    </Popover>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                    {messages.length === 0 && (
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
