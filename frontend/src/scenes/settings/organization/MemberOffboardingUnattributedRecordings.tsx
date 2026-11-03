import { useActions, useValues } from 'kea'

import { IconRewindPlay } from '@posthog/icons'
import { LemonBanner, LemonDialog, LemonSkeleton, LemonSwitch, LemonTable } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils/strings'

import { memberOffboardingLogic } from './memberOffboardingLogic'

export function MemberOffboardingUnattributedRecordings(): JSX.Element | null {
    const {
        unattributedRecordings,
        unattributedRecordingsLoading,
        removedLoading,
        savingResourcesLoading,
        unattributedRecordingsError,
        recordingRevocationRequested,
    } = useValues(memberOffboardingLogic)
    const { revokeUnattributedRecordings, loadUnattributedRecordings } = useActions(memberOffboardingLogic)

    if (unattributedRecordingsLoading && !unattributedRecordings) {
        return <LemonSkeleton className="mt-4 h-12" />
    }
    if (unattributedRecordingsError) {
        return (
            <LemonBanner
                className="mt-4"
                type="warning"
                action={{ children: 'Retry', onClick: loadUnattributedRecordings }}
            >
                Couldn't check public recording links with no known publisher. You can still remove the member.
            </LemonBanner>
        )
    }
    if (!unattributedRecordings?.count) {
        return null
    }
    const links = `${unattributedRecordings.count_is_capped ? 'more than ' : ''}${pluralize(
        unattributedRecordings.count,
        'public recording link'
    )}`

    return (
        <LemonTable
            className="mt-3"
            dataSource={[unattributedRecordings]}
            columns={[
                {
                    title: 'Resource name',
                    key: 'name',
                    render: () => (
                        <div className="flex items-center gap-2 min-w-0">
                            <IconRewindPlay className="shrink-0 text-xl text-secondary" />
                            <div className="min-w-0">
                                <span>{links}</span>
                                <div className="text-secondary text-xs">
                                    <Tooltip title="The publisher of these links is unknown. Some may have been shared by this member.">
                                        <span>Publisher unknown</span>
                                    </Tooltip>
                                </div>
                            </div>
                        </div>
                    ),
                },
                { title: 'Project', key: 'project', width: 124, render: () => 'All projects' },
                {
                    title: 'Publicly shared',
                    key: 'enabled',
                    width: 112,
                    render: () =>
                        recordingRevocationRequested ? (
                            <span className="text-secondary text-sm">Revocation requested</span>
                        ) : (
                            <LemonSwitch
                                checked
                                loading={unattributedRecordingsLoading}
                                disabledReason={
                                    removedLoading
                                        ? 'Removing member…'
                                        : savingResourcesLoading
                                          ? 'Saving changes…'
                                          : undefined
                                }
                                aria-label="Publicly shared recording links with unknown publishers"
                                data-attr="offboarding-revoke-unattributed-recordings"
                                onChange={() =>
                                    LemonDialog.open({
                                        title: `Revoke ${links}?`,
                                        description:
                                            'This turns off every public recording link with no known publisher across all projects in this organization. Anyone using these links loses access. The recordings stay in PostHog, and you can share them again.',
                                        primaryButton: {
                                            children: 'Revoke links',
                                            status: 'danger',
                                            onClick: revokeUnattributedRecordings,
                                        },
                                        secondaryButton: { children: 'Cancel' },
                                    })
                                }
                            />
                        ),
                },
            ]}
        />
    )
}
