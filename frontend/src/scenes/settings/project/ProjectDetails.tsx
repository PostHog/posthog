import { Label } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { ProjectNameAndLogo } from './ProjectNameAndLogo'
import { ProjectTags } from './ProjectTags'

export function ProjectDetails(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <div className="flex flex-col gap-4 max-w-160">
            <div className="flex flex-col gap-1">
                {todayRailNav ? <Label>Name & logo</Label> : <LemonLabel>Name & logo</LemonLabel>}
                <ProjectNameAndLogo />
            </div>
            <div className="flex flex-col gap-1">
                {todayRailNav ? <Label>Tags</Label> : <LemonLabel>Tags</LemonLabel>}
                <ProjectTags />
            </div>
        </div>
    )
}
