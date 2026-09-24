import { LemonInputSelect } from '@posthog/lemon-ui'

import { ProjectsLoadError } from './ProjectsLoadError'
import type { TeamSelectorProps } from './types'
import { createTeamOption } from './utils'

export const TeamSelector = ({
    teams,
    organizations,
    mode,
    value,
    onChange,
    loadFailed,
    onReload,
}: TeamSelectorProps): JSX.Element =>
    loadFailed ? (
        <ProjectsLoadError onReload={onReload} />
    ) : (
        <LemonInputSelect
            mode={mode}
            data-attr="teams"
            value={value}
            onChange={onChange}
            options={(teams || []).map((team) => createTeamOption(team, organizations))}
            loading={teams === undefined}
            placeholder={
                teams === undefined
                    ? 'Loading projects...'
                    : mode === 'single'
                      ? 'Select a project...'
                      : 'Select projects...'
            }
        />
    )
