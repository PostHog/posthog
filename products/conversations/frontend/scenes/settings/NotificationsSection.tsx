import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonButton, LemonCard, LemonDivider, Link } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { BrowserNotificationsSection } from './BrowserNotificationsSection'
import { supportSettingsLogic } from './supportSettingsLogic'

interface WorkflowTemplate {
    title: string
    description: string
    trigger: string
    // Id of the global workflow template in products/workflows/backend/templates
    templateId: string
}

// The highlights for a team getting started. The rest are one click away under "See all support templates".
const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
    {
        title: 'New ticket → Slack channel',
        description: 'Post a message to a chosen Slack channel whenever a customer opens a new ticket.',
        trigger: '$conversation_ticket_created',
        templateId: '019ce1f1-5d12-0000-e318-4b3ebd4b2aea',
    },
    {
        title: 'New ticket → AI triage and investigation',
        description:
            'An AI agent investigates each new ticket, tags and prioritizes it, and saves its findings and a suggested reply as a private note.',
        trigger: '$conversation_ticket_created',
        templateId: '01a12fb6-3cfe-0000-5d45-25a5b3a944e0',
    },
    {
        title: 'New ticket → acknowledge',
        description:
            'Reply on email and widget tickets to confirm you have them, so the customer can reply straight back.',
        trigger: '$conversation_ticket_created',
        templateId: '01a1352a-0c41-0000-6b1e-2f4e8a6d71c3',
    },
    {
        title: 'Customer reply → reopen ticket',
        description: 'Move pending, on hold and resolved tickets back to open when the customer replies.',
        trigger: '$conversation_message_received',
        templateId: '01a1352a-0c41-0000-1f8d-9b3a5c7e2d14',
    },
    {
        title: 'New ticket → first response SLA',
        description: "Set how soon your team should reply, based on the customer's plan, within your working hours.",
        trigger: '$conversation_ticket_created',
        templateId: '01a1352a-0c41-0000-5b93-e08a4c1f7d26',
    },
    {
        title: 'Resolved → CSAT email',
        description: 'A day after a ticket is resolved, email the customer a one-click satisfaction survey.',
        trigger: '$conversation_ticket_status_changed',
        templateId: '01a1352a-0c41-0000-3d7e-c2b9f05a1e68',
    },
]

export function NotificationsSection(): JSX.Element {
    const { setNotificationRecipients } = useActions(supportSettingsLogic)
    const { notificationRecipients } = useValues(supportSettingsLogic)

    return (
        <>
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <div className="flex items-center gap-4 justify-between">
                    <div>
                        <label className="w-40 shrink-0 font-medium">Email notifications</label>
                        <p className="text-xs text-muted-alt">
                            Team members who will receive email notifications when new tickets are created.
                        </p>
                    </div>
                    <MemberSelectMultiple
                        idKey="id"
                        value={notificationRecipients}
                        onChange={setNotificationRecipients}
                    />
                </div>
                <LemonDivider />
                <BrowserNotificationsSection />
            </LemonCard>

            <SceneSection
                title="Workflow templates"
                titleSize="sm"
                className="my-8"
                description={
                    <>
                        Build custom automations on top of support events.{' '}
                        <Link to={combineUrl(urls.workflows('templates'), { tagFilter: 'support' }).url}>
                            See all support templates
                        </Link>{' '}
                        ·{' '}
                        <Link to="https://posthog.com/docs/support/workflows" target="_blank">
                            Workflow docs
                        </Link>
                    </>
                }
            >
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-[800px]">
                    {WORKFLOW_TEMPLATES.map((template) => (
                        <LemonCard key={template.title} hoverEffect={false} className="flex flex-col gap-2 px-4 py-3">
                            <h4 className="font-semibold mb-0">{template.title}</h4>
                            <p className="text-xs text-muted-alt mb-1 flex-1">{template.description}</p>
                            <div className="flex items-center justify-between gap-2 mt-1">
                                <code className="text-xs text-muted-alt truncate">{template.trigger}</code>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    to={combineUrl(urls.workflowNew(), { templateId: template.templateId }).url}
                                >
                                    Use template
                                </LemonButton>
                            </div>
                        </LemonCard>
                    ))}
                </div>
            </SceneSection>
        </>
    )
}
