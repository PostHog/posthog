import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { TeamDisplayName } from 'scenes/settings/environment/TeamSettings'

import { ProjectTags } from './ProjectTags'

export function ProjectDetails(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-160">
            <div className="flex flex-col gap-1">
                <LemonLabel>Display name</LemonLabel>
                <TeamDisplayName />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Tags</LemonLabel>
                <ProjectTags />
            </div>
        </div>
    )
}
