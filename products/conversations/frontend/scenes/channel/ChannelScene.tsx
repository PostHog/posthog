import { useActions, useValues } from 'kea'

import { IconComment } from '@posthog/icons'
import { LemonButton, LemonCard, LemonCollapse, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { channelsLogic } from '../../channelsLogic'
import { ChatView } from '../../components/Chat/ChatView'
import { channelSceneLogic } from './channelSceneLogic'

export const scene: SceneExport<{ channelId: string }> = {
    component: ChannelScene,
    logic: channelSceneLogic,
    productKey: ProductKey.CONVERSATIONS,
    paramsToProps: ({ params: { channelId } }) => ({ channelId: channelId || '' }),
}

export function ChannelScene({ channelId }: { channelId: string }): JSX.Element {
    const logic = channelSceneLogic({ channelId })
    const { channel, channelLoading, chatMessages, messagesLoading, messageSending, members, draftContent } =
        useValues(logic)
    const { sendMessage, setDraftContent } = useActions(logic)
    const { joinChannel, leaveChannel } = useActions(channelsLogic)

    if (channelLoading) {
        return (
            <SceneContent>
                <div className="flex items-center justify-center h-96">
                    <Spinner className="text-4xl" />
                </div>
            </SceneContent>
        )
    }

    if (!channel) {
        return (
            <SceneContent>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <h2 className="text-xl font-semibold mb-2">Channel not found</h2>
                    </div>
                </div>
            </SceneContent>
        )
    }

    const isMember = channel.is_member

    return (
        <SceneContent>
            <SceneTitleSection
                name={`#${channel.name}`}
                description={channel.description || ''}
                resourceType={{ type: 'channel' }}
            />

            <div className="flex flex-col lg:flex-row items-start gap-4 mb-8">
                {/* Main chat area */}
                <div className="flex-1 min-w-0 max-w-full lg:max-w-[calc(100%-320px)]">
                    {isMember ? (
                        <ChatView
                            messages={chatMessages}
                            messagesLoading={messagesLoading}
                            messageSending={messageSending}
                            onSendMessage={(content, richContent, _isPrivate, onSuccess) =>
                                sendMessage(content, richContent, onSuccess)
                            }
                            draftContent={draftContent}
                            onDraftChange={setDraftContent}
                            minHeight="min(500px, calc(100svh - 320px))"
                            maxHeight="min(700px, calc(100svh - 320px))"
                        />
                    ) : (
                        <LemonCard hoverEffect={false} className="flex flex-col items-center justify-center p-8 gap-4">
                            <IconComment className="text-4xl text-muted-alt" />
                            <h3 className="text-lg font-semibold">#{channel.name}</h3>
                            {channel.description && <p className="text-muted-alt text-sm">{channel.description}</p>}
                            <LemonButton type="primary" onClick={() => joinChannel(channelId)}>
                                Join channel
                            </LemonButton>
                        </LemonCard>
                    )}
                </div>

                {/* Sidebar */}
                <div className="w-full lg:w-[300px] shrink-0">
                    <LemonCollapse
                        className="bg-surface-primary"
                        defaultActiveKeys={['channel-info', 'members']}
                        multiple
                        panels={[
                            {
                                key: 'channel-info',
                                header: 'Channel info',
                                content: (
                                    <div>
                                        <div className="space-y-2 text-xs">
                                            <div className="flex justify-between">
                                                <span className="text-muted-alt">Name</span>
                                                <span>#{channel.name}</span>
                                            </div>
                                            {channel.description && (
                                                <div className="flex justify-between gap-2">
                                                    <span className="text-muted-alt shrink-0">Description</span>
                                                    <span className="text-right truncate">{channel.description}</span>
                                                </div>
                                            )}
                                            <div className="flex justify-between">
                                                <span className="text-muted-alt">Members</span>
                                                <span>{channel.member_count}</span>
                                            </div>
                                        </div>
                                        {isMember && (
                                            <div className="mt-3 pt-3 border-t">
                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    fullWidth
                                                    center
                                                    onClick={() => leaveChannel(channelId)}
                                                >
                                                    Leave channel
                                                </LemonButton>
                                            </div>
                                        )}
                                    </div>
                                ),
                            },
                            {
                                key: 'members',
                                header: `Members (${members.length})`,
                                content: (
                                    <div className="space-y-1.5 max-h-64 overflow-y-auto">
                                        {members.map((member) => (
                                            <div key={member.id} className="flex items-center gap-2">
                                                <ProfilePicture
                                                    size="sm"
                                                    name={[member.first_name, member.last_name]
                                                        .filter(Boolean)
                                                        .join(' ')}
                                                    email={member.email}
                                                />
                                                <span className="text-xs truncate">
                                                    {[member.first_name, member.last_name].filter(Boolean).join(' ') ||
                                                        member.email}
                                                </span>
                                            </div>
                                        ))}
                                        {members.length === 0 && (
                                            <span className="text-xs text-muted-alt">No members yet</span>
                                        )}
                                    </div>
                                ),
                            },
                        ]}
                    />
                </div>
            </div>
        </SceneContent>
    )
}
