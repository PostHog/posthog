import { LemonButton, LemonDialog, LemonLabel, LemonSelect, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import { DataColorThemeModal } from './DataColorThemeModal'
import { dataColorThemesLogic } from './dataColorThemesLogic'

export function DataColorThemes(): JSX.Element {
    const { themes: _themes, themesLoading } = useValues(dataColorThemesLogic)
    const { selectTheme } = useActions(dataColorThemesLogic)

    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const themes = _themes || []

    // TODO: better way to detect the posthog default theme
    const defaultTheme = themes.find((theme) => theme.id === 1)

    return (
        <div className="space-y-4">
            <LemonTable
                loading={themesLoading}
                dataSource={themes}
                columns={[{ title: 'Name', dataIndex: 'name', key: 'name' }]}
            />
            <LemonButton type="secondary" onClick={() => selectTheme('new')}>
                Add theme
            </LemonButton>

            <LemonLabel id="default_theme">Default theme</LemonLabel>
            <LemonSelect
                value={currentTeam?.default_data_theme || defaultTheme?.id || null}
                onChange={(value) => {
                    const theme = themes.find((theme) => theme.id === value)
                    LemonDialog.open({
                        title: `Change the default data theme to "${theme.name}"?`,
                        description: 'This changes the default colors used when visualizing data in insights.',
                        primaryButton: {
                            children: 'Change default theme',
                            onClick: () => updateCurrentTeam({ default_data_theme: value }),
                        },
                        secondaryButton: {
                            children: 'Cancel',
                        },
                    })
                }}
                loading={themesLoading || currentTeamLoading}
                options={themes.map((theme) => ({ value: theme.id, label: theme.name }))}
            />

            <DataColorThemeModal />
        </div>
    )
}
