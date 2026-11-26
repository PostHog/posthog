import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { UserBasicType } from '~/types'

import { ProjectKeyLabel } from '../components/ProjectKeyLabel'
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
        return <ProjectKeyLabel id={projectKeyId} />
    }
    return <span className="text-muted">Unknown</span>
}
