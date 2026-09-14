import { LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { UserBasicType } from '~/types'

export function ModelMetadata({
    createdBy,
    createdAt,
    updatedAt,
    loading,
}: {
    createdBy?: UserBasicType | null
    createdAt?: string | null
    updatedAt?: string | null
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
                    ) : (
                        'Unknown'
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
        </dl>
    )
}
