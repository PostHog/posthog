import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { UserBasicType } from '~/types'

export function ModelMetadata({
    createdBy,
    createdByEmail,
    createdByLabel,
    createdAt,
    updatedAt,
    lastReadAt,
    loading,
}: {
    createdBy?: UserBasicType | null
    createdByEmail?: string | null
    createdByLabel?: string | null
    createdAt?: string | null
    updatedAt?: string | null
    lastReadAt?: string | null
    loading?: boolean
}): JSX.Element {
    return (
        <dl className="flex flex-wrap gap-x-8 gap-y-3 mb-0 text-sm" aria-label="Model metadata">
            <div>
                <dt className="text-secondary mb-1">Created by</dt>
                <dd className="mb-0">
                    {loading ? (
                        <LemonSkeleton className="h-5 w-20" />
                    ) : createdBy ? (
                        <ProfilePicture user={createdBy} showName size="sm" />
                    ) : createdByEmail ? (
                        <ProfilePicture user={{ email: createdByEmail }} showName size="sm" />
                    ) : (
                        (createdByLabel ?? 'Unknown')
                    )}
                </dd>
            </div>
            <div>
                <dt className="text-secondary mb-1">Created at</dt>
                <dd className="mb-0">
                    {loading ? (
                        <LemonSkeleton className="h-5 w-20" />
                    ) : createdAt ? (
                        <TZLabel time={createdAt} />
                    ) : (
                        'Unknown'
                    )}
                </dd>
            </div>
            {updatedAt && (
                <div>
                    <dt className="text-secondary mb-1">Updated at</dt>
                    <dd className="mb-0">
                        <TZLabel time={updatedAt} />
                    </dd>
                </div>
            )}
            {lastReadAt !== undefined && (
                <div>
                    <dt className="text-secondary mb-1">
                        <Tooltip title="The last time a query read this view, directly or through another view. This is updated once a day, so recent reads can take up to a day to show.">
                            <span>Last used</span>
                        </Tooltip>
                    </dt>
                    <dd className="mb-0 flex flex-wrap items-baseline gap-x-1">
                        {lastReadAt ? <TZLabel time={lastReadAt} /> : <span>Not in the last 60 days</span>}
                        <span className="text-secondary text-xs">(updated daily)</span>
                    </dd>
                </div>
            )}
        </dl>
    )
}
