import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { UserBasicType } from '~/types'

import type { HogFunctionRevisionBasicApi } from 'products/cdp/frontend/generated/api.schemas'

import { hogFunctionRevisionsLogic } from './hogFunctionRevisionsLogic'

export function HogFunctionRevisions({ id }: { id: string }): JSX.Element {
    const logic = hogFunctionRevisionsLogic({ id })
    const {
        revisions,
        revisionsCount,
        revisionsResponseLoading,
        restoringVersion,
        liveVersion,
        restoreDisabledReason,
    } = useValues(logic)
    const { restoreRevision } = useActions(logic)

    return (
        <div className="flex flex-col gap-2">
            <div>
                <h3 className="mb-0">Versions</h3>
                <p className="text-secondary mb-0">
                    A version is saved each time the live destination changes. Restore one to open it as a draft, then
                    publish it to go live.
                </p>
            </div>
            <LemonTable<HogFunctionRevisionBasicApi>
                dataSource={revisions}
                loading={revisionsResponseLoading}
                rowKey="version"
                footer={
                    revisionsCount > revisions.length ? (
                        <div className="px-3 py-2 text-xs text-secondary">
                            Showing the newest {revisions.length} of {revisionsCount} versions.
                        </div>
                    ) : undefined
                }
                emptyState="No versions yet. One is saved each time the live destination changes."
                columns={[
                    {
                        title: 'Version',
                        key: 'version',
                        render: (_, revision) => (
                            <span className="flex items-center gap-2 font-semibold">
                                v{revision.version}
                                {revision.version === liveVersion && <LemonTag type="success">Live</LemonTag>}
                            </span>
                        ),
                    },
                    {
                        title: 'Changed by',
                        key: 'created_by',
                        render: (_, revision) =>
                            revision.created_by ? (
                                <span className="flex items-center gap-2">
                                    {/* The generated hedgehog_config shape differs from the app type in
                                        ways ProfilePicture never reads; the display fields match. */}
                                    <ProfilePicture user={revision.created_by as UserBasicType} size="md" showName />
                                </span>
                            ) : (
                                <span className="text-secondary">API or system</span>
                            ),
                    },
                    {
                        title: 'Date',
                        key: 'created_at',
                        render: (_, revision) => <TZLabel time={revision.created_at} />,
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, revision) => (
                            // The flex wrapper keeps the button at its intrinsic height instead of
                            // stretching to the (avatar-driven) row height.
                            <div className="flex items-center">
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    className="whitespace-nowrap"
                                    onClick={() => restoreRevision(revision.version)}
                                    loading={restoringVersion === revision.version}
                                    disabledReason={
                                        revision.version === liveVersion
                                            ? 'This is the live version'
                                            : restoringVersion === revision.version
                                              ? undefined
                                              : restoreDisabledReason
                                    }
                                    data-attr="hog-function-revision-restore"
                                >
                                    Restore as draft
                                </LemonButton>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
