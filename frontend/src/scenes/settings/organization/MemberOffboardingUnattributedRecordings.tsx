import { useActions, useValues } from 'kea'

import { LemonBanner, LemonDialog, LemonSkeleton } from '@posthog/lemon-ui'

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
    if (recordingRevocationRequested) {
        return (
            <LemonBanner className="mt-4" type="info">
                Revocation requested. Turning off these public recording links can take a few minutes.
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
        <LemonBanner
            className="mt-4"
            type="info"
            action={{
                children: 'Revoke all',
                status: 'danger',
                loading: unattributedRecordingsLoading,
                disabledReason: removedLoading
                    ? 'Removing member…'
                    : savingResourcesLoading
                      ? 'Saving changes…'
                      : undefined,
                'data-attr': 'offboarding-revoke-unattributed-recordings',
                onClick: () =>
                    LemonDialog.open({
                        title: `Revoke ${links}?`,
                        description:
                            'Anyone who opens these links, including tools that embed them, loses access. The recordings stay in PostHog, and you can share them again.',
                        primaryButton: {
                            children: 'Revoke links',
                            status: 'danger',
                            onClick: revokeUnattributedRecordings,
                        },
                        secondaryButton: { children: 'Cancel' },
                    }),
            }}
        >
            <span>{`This organization has ${links} with no known publisher. Some may have been shared by this member. Revoking turns off public sharing for all of them, in every project.`}</span>
        </LemonBanner>
    )
}
