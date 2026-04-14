import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { projectsGridLogic } from './projectsGridLogic'
import { ProjectsGridPicker } from './ProjectsGridPicker'

export function ProjectsGridToolbar(): JSX.Element {
    const { search } = useValues(projectsGridLogic)
    const { setSearch } = useActions(projectsGridLogic)

    return (
        <div className="flex items-center justify-between gap-4 pb-4">
            <LemonInput
                type="search"
                value={search}
                onChange={setSearch}
                placeholder="Search flags by name or key"
                className="max-w-80"
                data-attr="projects-grid-search"
            />
            <ProjectsGridPicker />
        </div>
    )
}
