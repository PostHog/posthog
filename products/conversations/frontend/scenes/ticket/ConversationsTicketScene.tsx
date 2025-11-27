import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconBolt, IconSend } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDivider, LemonInput, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ScenesTabs } from '../../components/ScenesTabs'
import { ticketDetail } from '../../data/ticketDetail'

export const scene: SceneExport = {
    component: ConversationsTicketScene,
}

const actorAccent: Record<'customer' | 'ai' | 'human', string> = {
    customer: 'bg-primary-highlight',
    ai: 'bg-success-highlight',
    human: 'bg-side',
}

export function ConversationsTicketScene(): JSX.Element {
    const { push } = useActions(router)

    return (
        <SceneContent className="space-y-5">
            <ScenesTabs />
            <SceneTitleSection
                name={`${ticketDetail.subject} (${ticketDetail.id})`}
                description={`Queue: ${ticketDetail.queue} • Created ${ticketDetail.createdAt}`}
                resourceType={{ type: 'conversation' }}
                forceBackTo={{
                    name: 'Ticket list',
                    path: urls.conversationsTickets(),
                    key: 'conversationsTickets',
                }}
                actions={
                    <div className="flex flex-wrap gap-2">
                        <LemonButton type="secondary" icon={<IconBolt />}>
                            Escalate
                        </LemonButton>
                        <LemonButton type="primary" icon={<IconSend />}>
                            Reply
                        </LemonButton>
                    </div>
                }
            />
            <section className="space-y-2">
                <div className="flex flex-wrap gap-2 text-sm text-muted-alt">
                    <span>Created {ticketDetail.createdAt}</span>
                    <span>•</span>
                    <span>Updated {ticketDetail.updatedAt}</span>
                    <span>•</span>
                    <span>Channel: {ticketDetail.channel}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                    <LemonTag type={ticketDetail.status === 'resolved' ? 'success' : 'warning'}>
                        {ticketDetail.status}
                    </LemonTag>
                    <LemonTag type={ticketDetail.priority === 'high' ? 'danger' : 'default'}>
                        {ticketDetail.priority} priority
                    </LemonTag>
                    <LemonTag type={ticketDetail.aiContainment ? 'success' : 'warning'}>
                        {ticketDetail.aiContainment ? 'AI contained' : 'Human fallback'}
                    </LemonTag>
                </div>
            </section>

            <div className="grid gap-4 lg:grid-cols-3">
                <div className="space-y-4 lg:col-span-2">
                    <LemonCard hoverEffect={false}>
                        <div className="mb-3 flex items-center justify-between">
                            <h3 className="text-lg font-semibold">Conversation</h3>
                            <LemonButton
                                size="small"
                                type="secondary"
                                to={urls.conversationsTickets() + `/${ticketDetail.id}?view=raw`}
                            >
                                View raw JSON
                            </LemonButton>
                        </div>
                        <div className="space-y-3 rounded border border-light bg-bg-300 p-3 max-h-[440px] overflow-y-auto">
                            {ticketDetail.timeline.map((message, index) => (
                                <div key={message.id}>
                                    <div
                                        className={`rounded px-3 py-2 ${actorAccent[message.actor]} ${
                                            message.actor === 'customer' ? 'border border-primary' : ''
                                        }`}
                                    >
                                        <div className="flex items-center gap-2 text-sm font-medium">
                                            <span>{message.author}</span>
                                            {message.role && (
                                                <span className="text-xs text-muted-alt">{message.role}</span>
                                            )}
                                            <span className="text-xs text-muted-alt">{message.timestamp}</span>
                                        </div>
                                        <p className="mt-1 text-sm text-primary-alt">{message.content}</p>
                                        {message.attachments && (
                                            <div className="mt-2 flex flex-wrap gap-2">
                                                {message.attachments.map((att) => (
                                                    <LemonTag key={att.name} type="muted">
                                                        {att.name}
                                                    </LemonTag>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    {index < ticketDetail.timeline.length - 1 && (
                                        <LemonDivider dashed className="my-3" />
                                    )}
                                </div>
                            ))}
                        </div>
                        <LemonDivider className="my-4" />
                        <div className="space-y-2">
                            <LemonInput prefix={<span>To</span>} value={ticketDetail.customer.name} disabled />
                            <LemonTextArea placeholder="Draft a reply…" minRows={4} />
                        </div>
                        <div className="mt-3 flex justify-end gap-2">
                            <LemonButton type="secondary">Schedule</LemonButton>
                            <LemonButton type="primary" icon={<IconSend />}>
                                Send reply
                            </LemonButton>
                        </div>
                    </LemonCard>
                </div>

                <div className="space-y-4">
                    <LemonCard hoverEffect={false}>
                        <div className="flex items-center justify-between">
                            <div>
                                <h3 className="text-lg font-semibold">AI insights</h3>
                                <p className="text-sm text-muted-alt">{ticketDetail.aiInsights.fallbackReason}</p>
                            </div>
                            <LemonTag type="warning">Fallback</LemonTag>
                        </div>
                        <p className="mt-3 text-sm text-primary-alt">{ticketDetail.aiInsights.summary}</p>
                        <div className="mt-3">
                            <h4 className="text-xs font-semibold uppercase text-muted-alt">Referenced content</h4>
                            <div className="mt-2 flex flex-wrap gap-2">
                                {ticketDetail.aiInsights.referencedContent.map((item) => (
                                    <LemonTag key={item} type="muted">
                                        {item}
                                    </LemonTag>
                                ))}
                            </div>
                        </div>
                        <div className="mt-4 space-y-2">
                            <h4 className="text-xs font-semibold uppercase text-muted-alt">Suggested reply</h4>
                            <LemonTextArea value={ticketDetail.aiInsights.suggestedReply} disabled minRows={3} />
                        </div>
                    </LemonCard>

                    <LemonCard hoverEffect={false}>
                        <div className="flex items-center justify-between">
                            <h3 className="text-lg font-semibold">Customer overview</h3>
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => push(urls.personByDistinctId('123'))}
                            >
                                View person
                            </LemonButton>
                        </div>
                        <div className="mt-3 space-y-2 text-sm">
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Name</span>
                                <span>{ticketDetail.customer.name}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Company</span>
                                <span>{ticketDetail.customer.company}</span>
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
                                <span>{ticketDetail.customer.mrr}</span>
                            </div>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2">
                            {ticketDetail.customer.tags.map((tag) => (
                                <LemonTag key={tag} type="muted">
                                    {tag}
                                </LemonTag>
                            ))}
                        </div>
                    </LemonCard>

                    <LemonCard hoverEffect={false}>
                        <h3 className="text-lg font-semibold">SLA & ownership</h3>
                        <div className="mt-3 space-y-2 text-sm">
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Policy</span>
                                <span>{ticketDetail.sla.policy}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Promise</span>
                                <span>{ticketDetail.sla.promise}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Time remaining</span>
                                <span>{ticketDetail.sla.timeRemaining}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-alt">Owner</span>
                                <span>{ticketDetail.assignedTo}</span>
                            </div>
                        </div>
                        <div className="mt-2">
                            <LemonTag
                                type={
                                    ticketDetail.sla.risk === 'on-track'
                                        ? 'success'
                                        : ticketDetail.sla.risk === 'at-risk'
                                          ? 'warning'
                                          : 'danger'
                                }
                            >
                                {ticketDetail.sla.risk}
                            </LemonTag>
                        </div>
                    </LemonCard>

                    <LemonCard hoverEffect={false}>
                        <h3 className="text-lg font-semibold">Recent events</h3>
                        <div className="mt-3 space-y-2 text-sm">
                            {ticketDetail.recentEvents.map((event) => (
                                <div key={event.id}>
                                    <div className="flex justify-between">
                                        <span>{event.description}</span>
                                        <span className="text-muted-alt">{event.ts}</span>
                                    </div>
                                    <LemonDivider dashed className="my-2" />
                                </div>
                            ))}
                        </div>
                    </LemonCard>

                    <LemonCard hoverEffect={false}>
                        <h3 className="text-lg font-semibold">Session recording</h3>
                        <p className="text-sm text-muted-alt">
                            {ticketDetail.sessionRecording.id} · {ticketDetail.sessionRecording.duration}
                        </p>
                        <div className="mt-3 rounded border border-dashed border-light bg-bg-300 p-4 text-center text-sm text-muted-alt">
                            Recording preview placeholder
                        </div>
                        <LemonButton className="mt-3 w-full" type="secondary" to={ticketDetail.sessionRecording.url}>
                            Open in replay
                        </LemonButton>
                    </LemonCard>
                </div>
            </div>
        </SceneContent>
    )
}
