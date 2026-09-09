import { useActions, useValues } from 'kea'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'
import { Button, Card, CardContent, Separator } from 'lib/ui/quill'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { BrowserNotificationsSection } from './BrowserNotificationsSection'
import { supportSettingsLogic } from './supportSettingsLogic'

interface WorkflowTemplate {
    title: string
    description: string
    trigger: string
}

const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
    {
        title: 'New ticket → Slack channel',
        description: 'Post a message to a chosen Slack channel whenever a customer opens a new ticket.',
        trigger: '$conversation_ticket_created',
    },
    {
        title: 'Team reply → email customer',
        description:
            'When a team member replies on a ticket, email the customer so they receive the response in their inbox.',
        trigger: '$conversation_message_sent',
    },
    {
        title: 'Customer message → notify team',
        description: 'When a customer sends a message on a ticket, notify the assigned teammate by email or Slack.',
        trigger: '$conversation_message_received',
    },
    {
        title: 'SLA: no response in 4h → escalate',
        description: 'If a ticket sits without a team reply for 4 hours, reassign to a lead and email the team.',
        trigger: '$conversation_ticket_created',
    },
    {
        title: 'First team reply → mark Pending',
        description: 'When a team member sends the first reply, automatically move the ticket to Pending.',
        trigger: '$conversation_message_sent',
    },
    {
        title: 'Resolved → CSAT email',
        description: 'When a ticket is resolved, wait an hour and email the customer a 1-question CSAT survey.',
        trigger: '$conversation_ticket_status_changed',
    },
    {
        title: 'VIP cohort → high priority + auto-assign',
        description: 'Tickets from your VIP cohort get bumped to high priority and routed to the on-call lead.',
        trigger: '$conversation_ticket_created',
    },
]

export function NotificationsSection(): JSX.Element {
    const { setNotificationRecipients } = useActions(supportSettingsLogic)
    const { notificationRecipients } = useValues(supportSettingsLogic)

    return (
        <>
            <Card size="sm" className="max-w-[800px]">
                <CardContent className="flex flex-col gap-y-2">
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
                    <Separator />
                    <BrowserNotificationsSection />
                </CardContent>
            </Card>

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
                        <Card key={template.title} size="sm">
                            <CardContent className="flex flex-col gap-2">
                                <h4 className="font-semibold mb-0">{template.title}</h4>
                                <p className="text-xs text-muted-alt mb-1 flex-1">{template.description}</p>
                                <div className="flex items-center justify-between gap-2 mt-1">
                                    <code className="text-xs text-muted-alt truncate">{template.trigger}</code>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        render={<LinkPrimitive to={urls.workflowNew()} />}
                                    >
                                        Create workflow
                                    </Button>
                                </div>
                            </CardContent>
                        </Card>
                    ))}
                </div>
            </SceneSection>
        </>
    )
}
