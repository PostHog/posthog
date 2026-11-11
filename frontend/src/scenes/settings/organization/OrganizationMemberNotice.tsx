import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { OrganizationMemberNoticeMessage } from '~/layout/navigation/OrganizationMemberNoticeMessage'

import { organizationMemberNoticeLogic } from './organizationMemberNoticeLogic'

const MESSAGE_MAX_LENGTH = 1000
const BUTTON_LABEL_MAX_LENGTH = 40

export function OrganizationMemberNotice(): JSX.Element {
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
            className="flex flex-col gap-3 max-w-160"
        >
            <LemonField
                name="message"
                label="Message"
                help="You can use HTML for formatting and links, like <b>, <i>, <ul>, <br> and <a href>. Styles, scripts and other tags are removed."
            >
                <LemonTextArea
                    maxLength={MESSAGE_MAX_LENGTH}
                    disabled={!!restrictionReason}
                    placeholder='For example: This is how we collect your data. <a href="https://example.com/policy">Read the policy</a>'
                    data-attr="organization-member-notice-message"
                />
            </LemonField>
            <div className="flex flex-wrap gap-3">
                <LemonField name="label" label="Button label" showOptional className="flex-1 min-w-48">
                    <LemonInput
                        maxLength={BUTTON_LABEL_MAX_LENGTH}
                        disabled={!!restrictionReason}
                        placeholder="Read the policy"
                        data-attr="organization-member-notice-label"
                    />
                </LemonField>
                <LemonField name="url" label="Button link" showOptional className="flex-[2] min-w-60">
                    <LemonInput
                        type="url"
                        disabled={!!restrictionReason}
                        placeholder="https://"
                        data-attr="organization-member-notice-url"
                    />
                </LemonField>
            </div>
            {draftMemberNotice && (
                <LemonField.Pure label="Preview">
                    <LemonBanner
                        type="info"
                        action={
                            draftMemberNotice.action
                                ? {
                                      to: draftMemberNotice.action.url,
                                      targetBlank: true,
                                      children: draftMemberNotice.action.label,
                                  }
                                : undefined
                        }
                    >
                        <OrganizationMemberNoticeMessage html={draftMemberNotice.message} />
                    </LemonBanner>
                </LemonField.Pure>
            )}
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    disabledReason={restrictionReason ?? (!hasUnsavedMemberNotice ? 'No changes to save' : undefined)}
                    loading={isMemberNoticeSubmitting}
                    data-attr="organization-member-notice-save"
                >
                    Save notice
                </LemonButton>
                {savedMemberNotice && (
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={removeMemberNotice}
                        disabledReason={restrictionReason ?? undefined}
                        loading={currentOrganizationLoading && !isMemberNoticeSubmitting}
                        data-attr="organization-member-notice-remove"
                    >
                        Remove notice
                    </LemonButton>
                )}
            </div>
        </Form>
    )
}
