import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { UserBasicType } from '~/types'

import type { ScoreDefinitionApi } from '../generated/api.schemas'

export function ScorerActor({
    user,
    projectKeyId,
}: {
    user: ScoreDefinitionApi['updated_by']
    projectKeyId: string | null
}): JSX.Element {
    if (user) {
        return <ProfilePicture user={user as UserBasicType} size="md" showName />
    }
    if (projectKeyId) {
        return <span title={projectKeyId}>Project key · {projectKeyId.slice(-8)}</span>
    }
    return <span className="text-muted">Unknown</span>
}
