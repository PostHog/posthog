import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { fullNameOrEmail } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { memberOffboardingLogic } from './memberOffboardingLogic'
import { MemberOffboardingResourceSection } from './MemberOffboardingResourceSection'

export function MemberOffboardingModal(): JSX.Element {
    const {
        member,
        resources,
        resourcesLoading,
        loadError,
        removedLoading,
        savingResourcesLoading,
        publicResources,
        subscriptions,
    } = useValues(memberOffboardingLogic)
    const { close, loadResources, remove } = useActions(memberOffboardingLogic)
    const { scopedApiKeys, scopedApiKeysLoading } = useValues(membersLogic)
    const { user } = useValues(userLogic)
    const isSelf = member?.user.uuid === user?.uuid
    const busyReason = removedLoading ? 'Removing member…' : savingResourcesLoading ? 'Saving changes…' : undefined
    const hasResources = !resourcesLoading && !loadError && !!resources?.length

    return (
        <LemonModal
            isOpen={!!member}
            onClose={busyReason ? undefined : close}
            title={
                isSelf
                    ? 'Leave organization?'
                    : `Remove ${member ? fullNameOrEmail(member.user) : 'member'} from organization?`
            }
            width={hasResources ? 720 : 576}
            footer={
                <>
                    <LemonButton type="secondary" onClick={close} disabledReason={busyReason}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        loading={removedLoading}
                        disabledReason={
                            busyReason ||
                            (resourcesLoading
                                ? 'Checking shared resources and subscriptions…'
                                : loadError || resources === null
                                  ? 'Load the resource review before continuing'
                                  : undefined)
                        }
                        onClick={remove}
                        data-attr="confirm-org-member-offboarding"
                    >
                        {isSelf ? 'Leave' : 'Remove'}
                    </LemonButton>
                </>
            }
        >
            <p>
                {isSelf
                    ? 'Are you sure you want to leave this organization? This cannot be undone. If you leave, you will no longer have access to this organization.'
                    : 'The user will no longer have access to this organization.'}
            </p>
            {resourcesLoading ? (
                <LemonSkeleton className="h-12" />
            ) : loadError ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: loadResources }}>
                    Couldn't load shared resources and subscriptions. Retry before continuing.
                </LemonBanner>
            ) : hasResources ? (
                <div className="space-y-6">
                    {publicResources.length > 0 && (
                        <MemberOffboardingResourceSection resources={publicResources} kind="public" />
                    )}
                    {subscriptions.length > 0 && (
                        <MemberOffboardingResourceSection resources={subscriptions} kind="subscriptions" />
                    )}
                </div>
            ) : null}
            {!scopedApiKeysLoading && !!scopedApiKeys?.keys.length && (
                <div className="mt-4">
                    <LemonBanner type="warning" className="mb-2">
                        The following personal API keys will lose access to this organization and will stop working
                        immediately. Check any services that depend on them before continuing.
                    </LemonBanner>
                    <LemonTable
                        dataSource={scopedApiKeys.keys}
                        columns={[
                            { title: 'Name', dataIndex: 'name', key: 'name' },
                            {
                                title: 'Last used',
                                dataIndex: 'last_used_at',
                                key: 'last_used_at',
                                render: (lastUsed) => (lastUsed ? <TZLabel time={lastUsed} /> : 'Never'),
                            },
                        ]}
                    />
                </div>
            )}
        </LemonModal>
    )
}
