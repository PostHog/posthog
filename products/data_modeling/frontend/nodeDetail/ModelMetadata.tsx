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
        <dl className="grid grid-cols-2 gap-x-8 gap-y-3 mb-0 ml-auto text-sm py-2" aria-label="Model metadata">
            <div className="col-start-2 row-start-1">
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
            <div className="col-start-2 row-start-2">
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
                <div className="col-start-1 row-start-2">
                    <dt className="text-secondary mb-1">Updated at</dt>
                    <dd className="mb-0">
                        <TZLabel time={updatedAt} />
                    </dd>
                </div>
            )}
        </dl>
    )
}
