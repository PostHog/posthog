import { Skeleton } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { ModelMetadataFacts } from './nodeDetailSceneLogic'
import { QuillModelFact } from './QuillModelFact'
import { QuillModelFacts } from './QuillModelFacts'

export function QuillModelMetadata({
    createdBy,
    createdByEmail,
    createdByLabel,
    createdAt,
    updatedAt,
    loading,
}: ModelMetadataFacts): JSX.Element {
    return (
        <QuillModelFacts label="Model metadata">
            <QuillModelFact label="Created by">
                {loading ? (
                    <Skeleton className="h-5 w-20" />
                ) : createdBy ? (
                    <ProfilePicture user={createdBy} showName size="sm" />
                ) : createdByEmail ? (
                    <ProfilePicture user={{ email: createdByEmail }} showName size="sm" />
                ) : (
                    (createdByLabel ?? 'Unknown')
                )}
            </QuillModelFact>
            <QuillModelFact label="Created at">
                {loading ? <Skeleton className="h-5 w-20" /> : createdAt ? <TZLabel time={createdAt} /> : 'Unknown'}
            </QuillModelFact>
            {updatedAt && (
                <QuillModelFact label="Updated at">
                    <TZLabel time={updatedAt} />
                </QuillModelFact>
            )}
        </QuillModelFacts>
    )
}
