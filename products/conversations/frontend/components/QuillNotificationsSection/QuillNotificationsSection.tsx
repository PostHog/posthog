import { combineUrl } from 'kea-router'

import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
    Field,
    FieldContent,
    FieldDescription,
    FieldTitle,
    Separator,
} from '@posthog/quill'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { UserBasicType } from '~/types'

import { BrowserNotificationsSection } from '../../scenes/settings/BrowserNotificationsSection'
import type { WorkflowTemplate } from '../../scenes/settings/NotificationsSection'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'

export function QuillNotificationsSection({
    workflowTemplates,
    notificationRecipients,
    onNotificationRecipientsChange,
}: {
    workflowTemplates: WorkflowTemplate[]
    notificationRecipients: number[]
    onNotificationRecipientsChange: (recipients: UserBasicType[]) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-6">
            <Card size="sm" className="max-w-200">
                <CardContent className="flex flex-col gap-3">
                    <Field>
                        <FieldContent>
                            <FieldTitle>Email notifications</FieldTitle>
                            <FieldDescription>
                                Team members who will receive email notifications when new tickets are created.
                            </FieldDescription>
                        </FieldContent>
                        <MemberSelectMultiple
                            idKey="id"
                            value={notificationRecipients}
                            onChange={onNotificationRecipientsChange}
                        />
                    </Field>
                    <Separator />
                    <BrowserNotificationsSection />
                </CardContent>
            </Card>

            <QuillSettingsSubsection
                title="Workflow templates"
                description={
                    <>
                        Build custom automations on top of support events.{' '}
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={
                                <LinkPrimitive
                                    to={combineUrl(urls.workflows('templates'), { tagFilter: 'support' }).url}
                                />
                            }
                        >
                            See all support templates
                        </Button>{' '}
                        ·{' '}
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to="https://posthog.com/docs/support/workflows" target="_blank" />}
                        >
                            Workflow docs
                        </Button>
                    </>
                }
            >
                <div className="@container max-w-200">
                    <div className="grid grid-cols-1 gap-3 @xl:grid-cols-2">
                        {workflowTemplates.map((template) => (
                            <Card key={template.title} size="sm">
                                <CardHeader>
                                    <CardTitle>{template.title}</CardTitle>
                                    <CardDescription>{template.description}</CardDescription>
                                </CardHeader>
                                <CardFooter className="mt-auto flex flex-wrap items-center justify-between gap-2">
                                    <code className="truncate text-xs text-muted-foreground">{template.trigger}</code>
                                    <Button
                                        variant="outline"
                                        nativeButton={false}
                                        render={
                                            <LinkPrimitive
                                                to={
                                                    combineUrl(urls.workflowNew(), { templateId: template.templateId })
                                                        .url
                                                }
                                            />
                                        }
                                    >
                                        Use template
                                    </Button>
                                </CardFooter>
                            </Card>
                        ))}
                    </div>
                </div>
            </QuillSettingsSubsection>
        </div>
    )
}
