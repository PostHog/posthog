import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button, Card, CardContent, Field, FieldDescription, FieldLabel, Input } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { supportSettingsLogic } from '../../scenes/settings/supportSettingsLogic'

export function QuillAddEmailForm(): JSX.Element {
    const { newEmailFromEmail, newEmailFromName, emailConnecting, addEmailFormVisible } =
        useValues(supportSettingsLogic)
    const { setNewEmailFromEmail, setNewEmailFromName, connectEmail, setAddEmailFormVisible } =
        useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })
    const emailId = useId()

    if (!addEmailFormVisible) {
        return (
            <div>
                <Button
                    variant="outline"
                    onClick={() => setAddEmailFormVisible(true)}
                    disabledReason={adminRestrictionReason}
                >
                    <IconPlus />
                    Add email address
                </Button>
            </div>
        )
    }

    return (
        <Card size="sm">
            <CardContent className="flex flex-col gap-2">
                <Field>
                    <FieldLabel htmlFor={emailId}>Connect new email</FieldLabel>
                    <FieldDescription>
                        Enter the email address customers will contact you at (e.g. support@company.com). We'll give you
                        a forwarding address to set up in your email provider and register your domain for outbound
                        sending.
                    </FieldDescription>
                    <Input
                        id={emailId}
                        value={newEmailFromEmail}
                        onChange={(event) => setNewEmailFromEmail(event.target.value)}
                        placeholder="support@company.com"
                    />
                    <Input
                        aria-label="Display name"
                        value={newEmailFromName}
                        onChange={(event) => setNewEmailFromName(event.target.value)}
                        placeholder="Display name (e.g. Acme Support)"
                    />
                </Field>
                <div className="flex flex-wrap gap-2">
                    <Button
                        variant="primary"
                        onClick={connectEmail}
                        loading={emailConnecting}
                        disabledReason={
                            adminRestrictionReason ??
                            (!newEmailFromEmail || !newEmailFromName
                                ? 'Enter email address and display name'
                                : undefined)
                        }
                    >
                        Connect email
                    </Button>
                    <Button variant="outline" onClick={() => setAddEmailFormVisible(false)}>
                        Cancel
                    </Button>
                </div>
            </CardContent>
        </Card>
    )
}
