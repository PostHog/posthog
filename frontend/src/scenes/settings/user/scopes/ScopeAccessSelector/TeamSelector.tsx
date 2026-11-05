import { LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import type { TeamSelectorProps } from './types'
import { createTeamOption } from './utils'

export const TeamSelector = ({ teams, organizations, mode, value, onChange }: TeamSelectorProps): JSX.Element => {
    const options = (teams || []).map((team) => createTeamOption(team, organizations))

    return mode === 'single' ? (
        <LemonSelect
            fullWidth
            data-attr="teams"
            value={value?.[0]}
            onChange={(teamId) => onChange?.(teamId ? [teamId] : [])}
            options={options.map(({ key, label }) => ({ value: key, label }))}
            loading={teams === undefined}
            placeholder="Select a project..."
        />
    ) : (
        <LemonInputSelect
            mode="multiple"
            data-attr="teams"
            value={value}
            onChange={onChange}
            options={options}
            loading={teams === undefined}
            placeholder="Select projects..."
        />
    )
}
