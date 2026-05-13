import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'

import { SectionTrigger } from '~/layout/panel-layout/ai-first/Nav'
import { NavLink } from '~/layout/panel-layout/ai-first/NavLink'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { channelsLogic } from '../../channelsLogic'

function IconHash({ className }: { className?: string }): JSX.Element {
    return (
        <svg
            className={className}
            xmlns="http://www.w3.org/2000/svg"
            width="0.8em"
            height="0.8em"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            <line x1="4" y1="9" x2="20" y2="9" />
            <line x1="4" y1="15" x2="20" y2="15" />
            <line x1="10" y1="3" x2="8" y2="21" />
            <line x1="16" y1="3" x2="14" y2="21" />
        </svg>
    )
}

export function ChannelsNavSection(): JSX.Element {
    const { toggleNavSection } = useActions(panelLayoutLogic)
    const { expandedNavSections, isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { channels, channelsLoading } = useValues(channelsLogic)
    const { createChannel } = useActions(channelsLogic)
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [newChannelName, setNewChannelName] = useState('')

    const sortedChannels = [...channels].sort((a, b) => {
        if (a.is_default && !b.is_default) {
            return -1
        }
        if (!a.is_default && b.is_default) {
            return 1
        }
        return a.name.localeCompare(b.name)
    })

    const myChannels = sortedChannels.filter((c) => c.is_member)

    return (
        <>
            <Collapsible
                open={expandedNavSections.channels ?? true}
                onOpenChange={() => {
                    posthog.capture('nav section toggled', {
                        section: 'channels',
                        is_open: !expandedNavSections.channels,
                    })
                    toggleNavSection('channels')
                }}
                className="mt-2"
                data-attr="nav-section-channels"
            >
                <div className="relative">
                    <SectionTrigger label="Channels" isCollapsed={isLayoutNavCollapsed} />
                    {(expandedNavSections.channels ?? true) && (
                        <ButtonPrimitive
                            iconOnly
                            size="xs"
                            tooltip="Create channel"
                            tooltipPlacement="top"
                            onClick={() => setShowCreateModal(true)}
                            data-attr="nav-channels-add-button"
                            className="absolute right-1 top-0 bottom-0 my-auto rounded-[var(--radius)] z-5"
                        >
                            <IconPlus className="size-3 text-secondary" />
                        </ButtonPrimitive>
                    )}
                </div>
                <Collapsible.Panel className="pl-2 pt-1">
                    {channelsLoading && myChannels.length === 0 ? (
                        <div className="flex items-center justify-center py-2">
                            <Spinner className="size-4" />
                        </div>
                    ) : myChannels.length === 0 ? (
                        <span className="text-xs text-tertiary px-2 py-1">No channels</span>
                    ) : (
                        myChannels.map((channel) => (
                            <NavLink
                                icon={<IconHash />}
                                key={channel.id}
                                to={`/channels/${channel.id}`}
                                label={channel.name}
                                isCollapsed={isLayoutNavCollapsed}
                                data-attr={`nav-channel-${channel.name}`}
                                onClick={() => posthog.capture('nav channel clicked', { channel: channel.name })}
                            />
                        ))
                    )}
                </Collapsible.Panel>
            </Collapsible>

            <LemonModal
                isOpen={showCreateModal}
                onClose={() => {
                    setShowCreateModal(false)
                    setNewChannelName('')
                }}
                title="Create channel"
                footer={
                    <>
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                setShowCreateModal(false)
                                setNewChannelName('')
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={!newChannelName.trim() ? 'Enter a channel name' : undefined}
                            onClick={() => {
                                createChannel(newChannelName.trim())
                                setShowCreateModal(false)
                                setNewChannelName('')
                            }}
                        >
                            Create
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-2">
                    <label className="text-sm font-medium">Channel name</label>
                    <LemonInput
                        placeholder="e.g. design-feedback"
                        value={newChannelName}
                        onChange={setNewChannelName}
                        autoFocus
                        onPressEnter={() => {
                            if (newChannelName.trim()) {
                                createChannel(newChannelName.trim())
                                setShowCreateModal(false)
                                setNewChannelName('')
                            }
                        }}
                    />
                </div>
            </LemonModal>
        </>
    )
}
