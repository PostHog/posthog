import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonButton, LemonCard, LemonDivider, Link } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { BrowserNotificationsSection } from './BrowserNotificationsSection'
import { supportSettingsLogic } from './supportSettingsLogic'

interface WorkflowTemplate {
    // Matches the global template ID in products/workflows/backend/templates/
    id: string
    title: string
    description: string
    trigger: string
}

const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
    {
        id: '019ce1f1-5d12-0000-e318-4b3ebd4b2aea',
        title: 'New ticket → Slack or email',
        description:
            'Post a message to a chosen Slack channel or email your support team whenever a customer opens a new ticket.',
        trigger: '$conversation_ticket_created',
    },
    {
        id: 'a638999a-bf53-4fde-af36-c85ad9827076',
        title: 'Team reply → email customer',
        description: 'When a team member replies on a ticket, email the customer to let them know a reply is waiting.',
        trigger: '$conversation_message_sent',
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
                        <Link to="https://posthog.com/docs/support/workflows" target="_blank">
                            Workflow docs
                        </Link>
                    </>
                }
            >
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-[800px]">
                    {WORKFLOW_TEMPLATES.map((template) => (
                        <LemonCard key={template.id} hoverEffect={false} className="flex flex-col gap-2 px-4 py-3">
                            <h4 className="font-semibold mb-0">{template.title}</h4>
                            <p className="text-xs text-muted-alt mb-1 flex-1">{template.description}</p>
                            <div className="flex items-center justify-between gap-2 mt-1">
                                <code className="text-xs text-muted-alt truncate">{template.trigger}</code>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    to={combineUrl(urls.workflowNew(), { templateId: template.id }).url}
                                >
                                    Create workflow
                                </LemonButton>
                            </div>
                        </LemonCard>
                    ))}
                </div>
            </SceneSection>
        </>
    )
}
