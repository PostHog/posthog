import { ProfilePicture, Spinner, Tooltip } from '@posthog/lemon-ui'
import { BuiltLogic, useActions, useValues } from 'kea'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { sessionRecordingsPlaylistLogicType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogicType'
import { userLogic } from 'scenes/userLogic'

import { aiFilterLogic } from './aiFilterLogic'

export function AiFilterThread({ logic }: { logic: BuiltLogic<sessionRecordingsPlaylistLogicType> }): JSX.Element {
    const { setFilters, resetFilters } = useActions(logic)
    const filterLogic = aiFilterLogic({ setFilters, resetFilters })
    const { messages, isLoading } = useValues(filterLogic)
    const { user } = useValues(userLogic)

    return (
        <>
            {(messages.length > 0 || isLoading) && (
                <div className="w-[min(44rem,100%)] relative">
                    {messages
                        .filter((message) => message.role !== 'system')
                        .map((message, index) => (
                            <div key={index} className=" my-2">
                                {message.role === 'user' ? (
                                    <>
                                        <div className="relative flex gap-2 flex-row-reverse ml-10 items-center">
                                            <Tooltip placement="right" title="You">
                                                <ProfilePicture
                                                    user={{ ...user, hedgehog_config: undefined }}
                                                    size="lg"
                                                    className="mt-1 border"
                                                />
                                            </Tooltip>
                                            <div className="border py-2 px-3 rounded-lg bg-surface-primary font-medium">
                                                <LemonMarkdown>{message.content}</LemonMarkdown>
                                            </div>
                                        </div>
                                    </>
                                ) : (
                                    <>
                                        <div className="relative flex gap-2 mr-10 items-center">
                                            <Tooltip placement="left" title="Max">
                                                <ProfilePicture
                                                    user={{
                                                        hedgehog_config: {
                                                            ...user?.hedgehog_config,
                                                            use_as_profile: true,
                                                        },
                                                    }}
                                                    size="lg"
                                                    className="mt-1 border"
                                                />
                                            </Tooltip>
                                            <div className="border py-2 px-3 rounded-lg bg-surface-primary font-medium">
                                                <LemonMarkdown>{message.content}</LemonMarkdown>
                                            </div>
                                        </div>
                                    </>
                                )}
                            </div>
                        ))}
                    {isLoading && (
                        <div className="relative flex gap-2 mr-10 items-center">
                            <Tooltip placement="left" title="Max">
                                <ProfilePicture
                                    user={{ hedgehog_config: { ...user?.hedgehog_config, use_as_profile: true } }}
                                    size="lg"
                                    className="mt-1 border"
                                />
                            </Tooltip>
                            <div className="border py-2 px-3 rounded-lg bg-surface-primary font-medium">
                                Thinking...
                                <Spinner />
                            </div>
                        </div>
                    )}
                </div>
            )}
        </>
    )
}
