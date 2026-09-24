import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { TeamDisplayName } from 'scenes/settings/environment/TeamSettings'

import { PROJECT_TAGS_TRIGGER_ID, ProjectTags } from './ProjectTags'

export function ProjectDetails(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-160">
            <div className="flex flex-col gap-1">
                <LemonLabel>Display name</LemonLabel>
                <TeamDisplayName />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel htmlFor={PROJECT_TAGS_TRIGGER_ID}>Tags</LemonLabel>
                <ProjectTags />
            </div>
        </div>
    )
}
