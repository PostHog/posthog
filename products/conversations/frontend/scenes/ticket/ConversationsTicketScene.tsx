import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { LemonButton, LemonCard, LemonDivider, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { CommentComposer } from 'scenes/comments/CommentComposer'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { TicketSlaState, TicketStatus } from '../../data/tickets'
import { ticketDetail } from '../../data/tickets'
import { conversationsTicketSceneLogic } from './conversationsTicketSceneLogic'

export const scene: SceneExport = {
    component: ConversationsTicketScene,
}

function calculateSLA(lastMessageTimestamp: string): { timeRemaining: string; risk: TicketSlaState } {
    // Mock SLA calculation: assuming 1 hour (60 min) response time
    const SLA_MINUTES = 60
    const now = new Date()
    const lastMessage = new Date()

    // Parse time from format like "08:14" and set to today
    const [hours, minutes] = lastMessageTimestamp.split(':').map(Number)
    lastMessage.setHours(hours, minutes, 0, 0)

    const elapsedMinutes = Math.floor((now.getTime() - lastMessage.getTime()) / 1000 / 60)
    const remainingMinutes = SLA_MINUTES - elapsedMinutes

    let risk: TicketSlaState
    if (remainingMinutes < 0) {
        risk = 'breached'
    } else if (remainingMinutes < 15) {
        risk = 'at-risk'
    } else {
        risk = 'on-track'
    }

    return {
        timeRemaining:
            remainingMinutes > 0 ? `${remainingMinutes} min remaining` : `${Math.abs(remainingMinutes)} min overdue`,
        risk,
    }
}

export function ConversationsTicketScene(): JSX.Element {
    const logic = conversationsTicketSceneLogic()
    const { status, priority, assignedTo } = useValues(logic)
    const { setStatus, setPriority, setAssignedTo } = useActions(logic)
    const { push } = useActions(router)

    const [isAiActive, setIsAiActive] = useState(!ticketDetail.aiContainment) // AI active if not contained (escalated)
    const [escalationReason, setEscalationReason] = useState('')

    // Auto-calculate SLA based on last customer message
    const lastCustomerMessage = [...ticketDetail.timeline].reverse().find((msg) => msg.actor === 'customer')
    const [slaData, setSlaData] = useState(calculateSLA(lastCustomerMessage?.timestamp || '08:20'))

    useEffect(() => {
        const interval = setInterval(() => {
            if (lastCustomerMessage) {
                setSlaData(calculateSLA(lastCustomerMessage.timestamp))
            }
        }, 30000) // Update every 30 seconds

        return () => clearInterval(interval)
    }, [lastCustomerMessage])

    const handleEscalate = (): void => {
        // TODO: Add modal to collect escalation reason
        setIsAiActive(false)
        setEscalationReason('Requires human expertise')
        // TODO: Send to backend to stop AI responses and log escalation
    }

    const handleReenableAi = (): void => {
        setIsAiActive(true)
        setEscalationReason('')
        // TODO: Send to backend to re-enable AI responses
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={ticketDetail.subject}
                description={ticketDetail.id}
                resourceType={{ type: 'conversation' }}
                forceBackTo={{
                    name: 'Ticket list',
                    path: urls.conversationsTickets(),
                    key: 'conversationsTickets',
                }}
            />

            <div className="grid gap-4 lg:grid-cols-[1fr_380px] items-start">
                {/* Main conversation area */}
                <LemonCard hoverEffect={false} className="flex flex-col overflow-hidden">
                    {/* Chat messages */}
                    <div className="flex-1 overflow-y-auto p-4 space-y-1.5 min-h-[400px] max-h-[600px]">
                        {ticketDetail.timeline.map((message) => (
                            <div
                                key={message.id}
                                className={`flex ${message.actor === 'customer' ? 'flex-row-reverse ml-10' : 'mr-10'}`}
                            >
                                <div
                                    className={`flex flex-col min-w-0 ${message.actor === 'customer' ? 'items-end' : 'items-start'}`}
                                >
                                    <div className="max-w-full">
                                        <div className="border py-2 px-3 rounded-lg bg-surface-primary">
                                            <div className="flex items-center gap-2 text-xs text-muted mb-1">
                                                <span className="font-medium">{message.author}</span>
                                                {message.role && (
                                                    <span className="text-muted-alt">· {message.role}</span>
                                                )}
                                                <span className="text-muted-alt">· {message.timestamp}</span>
                                            </div>
                                            <p className="text-sm">{message.content}</p>
                                            {message.attachments && (
                                                <div className="mt-2 flex flex-wrap gap-1.5">
                                                    {message.attachments.map((att) => (
                                                        <LemonTag key={att.name} type="muted" size="small">
                                                            {att.name}
                                                        </LemonTag>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        ))}

                        {/* Escalation indicator */}
                        {!isAiActive && escalationReason && (
                            <div className="flex justify-center my-3">
                                <div className="bg-warning-highlight border border-warning rounded px-3 py-2 text-xs">
                                    <span className="font-medium">🤝 Escalated to human</span>
                                    <span className="text-muted-alt ml-2">· {escalationReason}</span>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Reply input */}
                    <div className="border-t p-3">
                        <CommentComposer scope="conversation_ticket" item_id={ticketDetail.id} />
                    </div>
                </LemonCard>

                {/* Sidebar with all metadata */}
                <div className="space-y-3">
                    {/* Ticket info */}
                    <LemonCard hoverEffect={false} className="p-3">
                        <h3 className="text-sm font-semibold mb-2">Ticket info</h3>
                        <div className="space-y-2 text-xs">
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Created</span>
                                <span>{ticketDetail.createdAt}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Updated</span>
                                <span>{ticketDetail.updatedAt}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Channel</span>
                                <span className="capitalize">{ticketDetail.channel}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Queue</span>
                                <span>{ticketDetail.queue}</span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Handling</span>
                                <LemonTag type={isAiActive ? 'success' : 'default'} size="small">
                                    {isAiActive ? 'AI active' : 'Human'}
                                </LemonTag>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Status</span>
                                <LemonSelect
                                    size="small"
                                    value={status}
                                    options={[
                                        { value: 'open', label: 'Open' },
                                        { value: 'pending', label: 'Pending' },
                                        { value: 'resolved', label: 'Resolved' },
                                    ]}
                                    onChange={(value: TicketStatus | null) => value && setStatus(value)}
                                    dropdownMatchSelectWidth={false}
                                />
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Priority</span>
                                <LemonSelect
                                    size="small"
                                    value={priority}
                                    options={[
                                        { value: 'low', label: 'Low' },
                                        { value: 'medium', label: 'Medium' },
                                        { value: 'high', label: 'High' },
                                    ]}
                                    onChange={(value: 'low' | 'medium' | 'high' | null) => value && setPriority(value)}
                                    dropdownMatchSelectWidth={false}
                                />
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">Assignee</span>
                                <LemonInput
                                    className="max-w-32"
                                    size="small"
                                    value={assignedTo}
                                    onChange={(value) => setAssignedTo(value)}
                                    placeholder="Unassigned"
                                />
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt">SLA</span>
                                <LemonTag
                                    type={
                                        slaData.risk === 'on-track'
                                            ? 'success'
                                            : slaData.risk === 'at-risk'
                                              ? 'warning'
                                              : 'danger'
                                    }
                                    size="small"
                                >
                                    {slaData.timeRemaining}
                                </LemonTag>
                            </div>
                        </div>
                    </LemonCard>

                    {/* AI insights */}
                    <LemonCard hoverEffect={false} className="p-3">
                        <div className="flex items-center justify-between mb-2">
                            <h3 className="text-sm font-semibold">AI insights</h3>
                            <LemonTag type={isAiActive ? 'success' : 'warning'} size="small">
                                {isAiActive ? 'Active' : 'Escalated'}
                            </LemonTag>
                        </div>

                        {isAiActive ? (
                            <>
                                <p className="text-xs text-muted-alt mb-3">AI is actively handling this conversation</p>
                                <LemonButton type="secondary" size="small" fullWidth onClick={handleEscalate}>
                                    Escalate to human
                                </LemonButton>
                            </>
                        ) : (
                            <>
                                <p className="text-xs text-muted-alt mb-2">{ticketDetail.aiInsights.fallbackReason}</p>
                                <p className="text-xs mb-2">{ticketDetail.aiInsights.summary}</p>
                                <div className="space-y-1.5 mb-3">
                                    <h4 className="text-xs font-medium text-muted-alt">Referenced content</h4>
                                    <div className="flex flex-wrap gap-1">
                                        {ticketDetail.aiInsights.referencedContent.map((item) => (
                                            <LemonTag key={item} type="muted" size="small">
                                                {item}
                                            </LemonTag>
                                        ))}
                                    </div>
                                </div>
                                <div className="space-y-1.5 mb-3">
                                    <h4 className="text-xs font-medium text-muted-alt">Suggested reply</h4>
                                    <div className="text-xs p-2 bg-bg-300 rounded border text-muted-alt">
                                        {ticketDetail.aiInsights.suggestedReply}
                                    </div>
                                </div>
                                <LemonButton type="secondary" size="small" fullWidth onClick={handleReenableAi}>
                                    Re-enable AI
                                </LemonButton>
                            </>
                        )}
                    </LemonCard>

                    {/* Customer */}
                    <LemonCard hoverEffect={false} className="p-3">
                        <div className="flex items-center justify-between mb-2">
                            <h3 className="text-sm font-semibold">Customer</h3>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={() => push(urls.personByDistinctId('123'))}
                            >
                                View person
                            </LemonButton>
                        </div>
                        <div className="space-y-1.5 text-xs">
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Name</span>
                                <span className="font-medium">{ticketDetail.customer.name}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Company</span>
                                <span className="font-medium">{ticketDetail.customer.company}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Plan</span>
                                <span>{ticketDetail.customer.plan}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Region</span>
                                <span>{ticketDetail.customer.region}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">ARR</span>
                                <span className="font-medium">{ticketDetail.customer.mrr}</span>
                            </div>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1">
                            {ticketDetail.customer.tags.map((tag) => (
                                <LemonTag key={tag} type="muted" size="small">
                                    {tag}
                                </LemonTag>
                            ))}
                        </div>
                    </LemonCard>

                    {/* Recent events */}
                    <LemonCard hoverEffect={false} className="p-3">
                        <h3 className="text-sm font-semibold mb-2">Recent events</h3>
                        <div className="space-y-2 text-xs">
                            {ticketDetail.recentEvents.map((event, idx) => (
                                <div key={event.id}>
                                    <div className="flex justify-between gap-2">
                                        <span className="flex-1">{event.description}</span>
                                        <span className="text-muted-alt whitespace-nowrap">{event.ts}</span>
                                    </div>
                                    {idx < ticketDetail.recentEvents.length - 1 && (
                                        <LemonDivider dashed className="my-2" />
                                    )}
                                </div>
                            ))}
                        </div>
                    </LemonCard>

                    {/* Session recording */}
                    <LemonCard hoverEffect={false} className="p-3">
                        <h3 className="text-sm font-semibold mb-2">Session recording</h3>
                        <p className="text-xs text-muted-alt mb-2">
                            {ticketDetail.sessionRecording.id} · {ticketDetail.sessionRecording.duration}
                        </p>
                        <div className="rounded border border-dashed border-light bg-bg-300 p-3 text-center text-xs text-muted-alt">
                            Recording preview
                        </div>
                        <LemonButton
                            className="mt-2 w-full"
                            type="secondary"
                            size="small"
                            to={ticketDetail.sessionRecording.url}
                        >
                            Open in replay
                        </LemonButton>
                    </LemonCard>

                    {/* Previous tickets */}
                    <LemonCard hoverEffect={false} className="p-3">
                        <h3 className="text-sm font-semibold mb-2">Previous tickets</h3>
                        <div className="space-y-2 text-xs">
                            <div className="p-2 rounded border border-border-light hover:bg-bg-light cursor-pointer">
                                <div className="font-medium">Widget rendering issue</div>
                                <div className="text-muted-alt mt-0.5">Resolved • 3 days ago</div>
                            </div>
                            <div className="p-2 rounded border border-border-light hover:bg-bg-light cursor-pointer">
                                <div className="font-medium">API rate limit question</div>
                                <div className="text-muted-alt mt-0.5">Resolved • 1 week ago</div>
                            </div>
                            <div className="p-2 rounded border border-border-light hover:bg-bg-light cursor-pointer">
                                <div className="font-medium">SAML configuration help</div>
                                <div className="text-muted-alt mt-0.5">Resolved • 2 weeks ago</div>
                            </div>
                        </div>
                        <LemonButton className="mt-2 w-full" type="secondary" size="small">
                            View all tickets
                        </LemonButton>
                    </LemonCard>
                </div>
            </div>
        </SceneContent>
    )
}
