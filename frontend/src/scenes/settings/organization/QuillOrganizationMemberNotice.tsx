import { useActions, useValues } from 'kea'
import { Form, Field as KeaField } from 'kea-forms'
import { ReactElement } from 'react'

import {
    Button,
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Label,
    Text,
    Textarea,
} from '@posthog/quill'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { OrganizationMemberNoticeMessage } from '~/layout/navigation/OrganizationMemberNoticeMessage'

import { organizationMemberNoticeLogic } from './organizationMemberNoticeLogic'

const MESSAGE_MAX_LENGTH = 1000
const BUTTON_LABEL_MAX_LENGTH = 40

function NoticeField({
    name,
    label,
    optional,
    help,
    className,
    children,
}: {
    name: string
    label: string
    optional?: boolean
    help?: string
    className?: string
    children: (control: { id: string; value: string; onChange: (value: string) => void }) => ReactElement
}): JSX.Element {
    return (
        <KeaField name={name} noStyle>
            {({ id, value, onChange, error }) => (
                <Field data-invalid={error ? true : undefined} className={className}>
                    <FieldLabel htmlFor={id}>
                        {label}
                        {optional && (
                            <Text size="xs" variant="muted" render={<span />} className="m-0">
                                (optional)
                            </Text>
                        )}
                    </FieldLabel>
                    {children({ id, value: value ?? '', onChange })}
                    {help && <FieldDescription>{help}</FieldDescription>}
                    {error && <FieldError>{error}</FieldError>}
                </Field>
            )}
        </KeaField>
    )
}

export function QuillOrganizationMemberNotice(): JSX.Element {
    const {
        draftMemberNotice,
        savedMemberNotice,
        hasUnsavedMemberNotice,
        isMemberNoticeSubmitting,
        currentOrganizationLoading,
    } = useValues(organizationMemberNoticeLogic)
    const { removeMemberNotice } = useActions(organizationMemberNoticeLogic)

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    return (
        <Form
            logic={organizationMemberNoticeLogic}
            formKey="memberNotice"
            enableFormOnSubmit
            className="flex flex-col gap-4 max-w-160"
        >
            <NoticeField
                name="message"
                label="Message"
                help="You can use HTML for formatting and links, like <b>, <i>, <ul>, <br> and <a href>. Styles, scripts and other tags are removed."
            >
                {({ id, value, onChange }) => (
                    <Textarea
                        id={id}
                        value={value}
                        onChange={(event) => onChange(event.target.value)}
                        maxLength={MESSAGE_MAX_LENGTH}
                        disabledReason={restrictionReason}
                        placeholder='For example: This is how we collect your data. <a href="https://example.com/policy">Read the policy</a>'
                        data-attr="organization-member-notice-message"
                    />
                )}
            </NoticeField>
            <div className="flex flex-wrap gap-4">
                <NoticeField name="label" label="Button label" optional className="flex-1 min-w-48 w-auto">
                    {({ id, value, onChange }) => (
                        <Input
                            id={id}
                            value={value}
                            onChange={(event) => onChange(event.target.value)}
                            maxLength={BUTTON_LABEL_MAX_LENGTH}
                            disabledReason={restrictionReason}
                            placeholder="Read the policy"
                            data-attr="organization-member-notice-label"
                        />
                    )}
                </NoticeField>
                <NoticeField name="url" label="Button link" optional className="flex-2 min-w-60 w-auto">
                    {({ id, value, onChange }) => (
                        <Input
                            id={id}
                            type="url"
                            value={value}
                            onChange={(event) => onChange(event.target.value)}
                            disabledReason={restrictionReason}
                            placeholder="https://"
                            data-attr="organization-member-notice-url"
                        />
                    )}
                </NoticeField>
            </div>
            {draftMemberNotice && (
                <div className="flex flex-col gap-2">
                    <Label>Preview</Label>
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                <OrganizationMemberNoticeMessage html={draftMemberNotice.message} />
                            </ItemDescription>
                        </ItemContent>
                        {draftMemberNotice.action && (
                            <ItemActions>
                                <Button
                                    variant="outline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={draftMemberNotice.action.url} target="_blank" />}
                                >
                                    {draftMemberNotice.action.label}
                                </Button>
                            </ItemActions>
                        )}
                    </Item>
                </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
                <Button
                    variant="primary"
                    type="submit"
                    disabledReason={restrictionReason ?? (!hasUnsavedMemberNotice ? 'No changes to save' : undefined)}
                    loading={isMemberNoticeSubmitting}
                    data-attr="organization-member-notice-save"
                >
                    Save notice
                </Button>
                {savedMemberNotice && (
                    <Button
                        variant="destructive-outline"
                        onClick={removeMemberNotice}
                        disabledReason={restrictionReason ?? undefined}
                        loading={currentOrganizationLoading && !isMemberNoticeSubmitting}
                        data-attr="organization-member-notice-remove"
                    >
                        Remove notice
                    </Button>
                )}
            </div>
        </Form>
    )
}
