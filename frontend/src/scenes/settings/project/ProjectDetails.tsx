import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { ProjectNameAndLogo } from './ProjectNameAndLogo'
import { ProjectTags } from './ProjectTags'

export function ProjectDetails(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-160">
            <div className="flex flex-col gap-1">
                <LemonLabel>Name & logo</LemonLabel>
                <ProjectNameAndLogo />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Tags</LemonLabel>
                <ProjectTags />
            </div>
        </div>
    )
}
