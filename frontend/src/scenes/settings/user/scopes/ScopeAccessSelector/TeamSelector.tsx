import { LemonInputSelect } from '@posthog/lemon-ui'

import type { TeamSelectorProps } from './types'
import { createTeamOption } from './utils'

export const TeamSelector = ({ teams, organizations, mode, value, onChange }: TeamSelectorProps): JSX.Element => (
    <LemonInputSelect
        mode={mode}
        data-attr="teams"
        value={value}
        onChange={onChange}
        options={(teams || []).map((team) => createTeamOption(team, organizations))}
        loading={teams === undefined}
        placeholder={mode === 'single' ? 'Select a project...' : 'Select projects...'}
    />
)
