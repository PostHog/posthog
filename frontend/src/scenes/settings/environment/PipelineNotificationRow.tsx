import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonTag } from '@posthog/lemon-ui'

import { membershipLevelToName } from 'lib/utils/permissioning'

import type { PipelineItem } from '../shared/pipelineDiscovery'
import { pipelineNotificationAdminLogic } from './pipelineNotificationAdminLogic'

export function PipelineNotificationRow({ pipeline }: { pipeline: PipelineItem }): JSX.Element {
    const { members, isSubscribed, savingChanges, expandedPipelines } = useValues(pipelineNotificationAdminLogic)
    const { setSubscription, setSubscriptionForAllMembers, toggleExpandedPipeline } =
        useActions(pipelineNotificationAdminLogic)
    const expanded = !!expandedPipelines[pipeline.id]

    const listedMembers = members ?? []
    const subscribed = listedMembers.filter((member) => isSubscribed(member.user_id, pipeline.id))
    const subscribedWithEmailsOff = subscribed.filter((member) => !member.pipeline_emails_enabled)

    return (
        <div className="border rounded p-3 space-y-2">
            <div className="flex items-center justify-between gap-2">
                <LemonButton
                    icon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                    onClick={() => toggleExpandedPipeline(pipeline.id)}
                    size="small"
                    type="tertiary"
                    className="p-0"
                    data-attr="pipeline-notification-admin-expand"
                >
                    {pipeline.name}
                </LemonButton>
                <span className="text-muted text-xs">
                    {subscribed.length} of {listedMembers.length} receive emails
                </span>
            </div>

            {expanded && (
                <div className="ml-6 space-y-2">
                    <div className="flex flex-row items-center gap-4">
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={() => setSubscriptionForAllMembers(pipeline.id, true)}
                            data-attr="pipeline-notification-admin-subscribe-all"
                        >
                            Subscribe everyone
                        </LemonButton>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={() => setSubscriptionForAllMembers(pipeline.id, false)}
                            data-attr="pipeline-notification-admin-unsubscribe-all"
                        >
                            Unsubscribe everyone
                        </LemonButton>
                    </div>

                    {subscribedWithEmailsOff.length > 0 && (
                        <LemonBanner type="info">
                            Some of these members have turned off all data pipeline failure emails. Subscribing them
                            here takes effect once they turn their own setting back on.
                        </LemonBanner>
                    )}

                    <div className="flex flex-col gap-1">
                        {listedMembers.map((member) => {
                            const name = `${member.first_name} ${member.last_name}`.trim()
                            return (
                                <LemonCheckbox
                                    key={member.user_id}
                                    id={`pipeline-notification-${pipeline.id}-${member.user_id}`}
                                    data-attr="pipeline-notification-admin-member"
                                    checked={isSubscribed(member.user_id, pipeline.id)}
                                    onChange={(checked) => setSubscription(member.user_id, pipeline.id, checked)}
                                    disabledReason={
                                        !member.editable
                                            ? 'This member has a higher organization access level than you'
                                            : savingChanges
                                              ? 'Saving'
                                              : undefined
                                    }
                                    label={
                                        <div className="flex items-center gap-2">
                                            <span>{name || member.email}</span>
                                            {!!name && <span className="text-muted text-xs">{member.email}</span>}
                                            <LemonTag type="muted">
                                                {membershipLevelToName.get(member.organization_membership_level)}
                                            </LemonTag>
                                            {!member.pipeline_emails_enabled && (
                                                <LemonTag type="warning">All pipeline emails off</LemonTag>
                                            )}
                                        </div>
                                    }
                                />
                            )
                        })}
                    </div>
                </div>
            )}
        </div>
    )
}
