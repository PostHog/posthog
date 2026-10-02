import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { organizationLogic } from 'scenes/organizationLogic'

import type { OrganizationMemberNoticeApi } from '~/generated/core/api.schemas'
import { OrganizationMemberNoticeMessage } from '~/layout/navigation/OrganizationMemberNoticeMessage'

const MESSAGE_MAX_LENGTH = 1000
const BUTTON_LABEL_MAX_LENGTH = 40

function buildMemberNotice(message: string, label: string, url: string): OrganizationMemberNoticeApi | null {
    if (!message.trim()) {
        return null
    }
    return {
        message: message.trim(),
        action: label.trim() && url.trim() ? { label: label.trim(), url: url.trim() } : null,
    }
}

export function OrganizationMemberNotice(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const savedNotice = currentOrganization?.member_notice ?? null

    const [message, setMessage] = useState(savedNotice?.message ?? '')
    const [label, setLabel] = useState(savedNotice?.action?.label ?? '')
    const [url, setUrl] = useState(savedNotice?.action?.url ?? '')

    // Keep these in sync in case the notice changes outside of this component
    useEffect(() => {
        setMessage(savedNotice?.message ?? '')
        setLabel(savedNotice?.action?.label ?? '')
        setUrl(savedNotice?.action?.url ?? '')
    }, [savedNotice?.message, savedNotice?.action?.label, savedNotice?.action?.url])

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    const draftNotice = buildMemberNotice(message, label, url)
    const hasChanges =
        (draftNotice?.message ?? '') !== (savedNotice?.message ?? '') ||
        (draftNotice?.action?.label ?? '') !== (savedNotice?.action?.label ?? '') ||
        (draftNotice?.action?.url ?? '') !== (savedNotice?.action?.url ?? '')
    const hasHalfAButton = !!label.trim() !== !!url.trim()
    const hasInvalidUrl = !!url.trim() && !/^https?:\/\//i.test(url.trim())

    const saveDisabledReason =
        restrictionReason ??
        (!message.trim()
            ? 'Add a message'
            : hasHalfAButton
              ? 'Add both a button label and a link, or leave both empty'
              : hasInvalidUrl
                ? 'The link must start with http:// or https://'
                : !hasChanges
                  ? 'No changes to save'
                  : undefined)

    return (
        <div className="flex flex-col gap-3 max-w-160">
            <LemonField.Pure
                label="Message"
                help="You can use HTML for formatting and links, like <b>, <i>, <ul>, <br> and <a href>. Styles, scripts and other tags are removed."
            >
                <LemonTextArea
                    value={message}
                    onChange={setMessage}
                    maxLength={MESSAGE_MAX_LENGTH}
                    disabled={!!restrictionReason}
                    placeholder='For example: This is how we collect your data. <a href="https://example.com/policy">Read the policy</a>'
                    data-attr="organization-member-notice-message"
                />
            </LemonField.Pure>
            <div className="flex flex-wrap gap-3">
                <LemonField.Pure label="Button label" showOptional className="flex-1 min-w-48">
                    <LemonInput
                        value={label}
                        onChange={setLabel}
                        maxLength={BUTTON_LABEL_MAX_LENGTH}
                        disabled={!!restrictionReason}
                        placeholder="Read the policy"
                        data-attr="organization-member-notice-label"
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Button link" showOptional className="flex-[2] min-w-60">
                    <LemonInput
                        value={url}
                        onChange={setUrl}
                        type="url"
                        disabled={!!restrictionReason}
                        placeholder="https://"
                        data-attr="organization-member-notice-url"
                    />
                </LemonField.Pure>
            </div>
            {draftNotice && (
                <LemonField.Pure label="Preview">
                    <LemonBanner
                        type="info"
                        action={
                            draftNotice.action
                                ? { to: draftNotice.action.url, targetBlank: true, children: draftNotice.action.label }
                                : undefined
                        }
                    >
                        <OrganizationMemberNoticeMessage html={draftNotice.message} />
                    </LemonBanner>
                </LemonField.Pure>
            )}
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton
                    type="primary"
                    onClick={() => updateOrganization({ member_notice: draftNotice })}
                    disabledReason={saveDisabledReason}
                    loading={currentOrganizationLoading}
                    data-attr="organization-member-notice-save"
                >
                    Save
                </LemonButton>
                {savedNotice && (
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={() => updateOrganization({ member_notice: null })}
                        disabledReason={restrictionReason ?? undefined}
                        loading={currentOrganizationLoading}
                        data-attr="organization-member-notice-remove"
                    >
                        Remove notice
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
