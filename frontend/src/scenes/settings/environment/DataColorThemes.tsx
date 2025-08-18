import { useActions, useValues } from 'kea'

import { IconBadge } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonLabel, LemonSelect, LemonTable, Link } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { teamLogic } from 'scenes/teamLogic'

import { AvailableFeature } from '~/types'

import { DataColorThemeModal } from './DataColorThemeModal'
import { dataColorThemesLogic } from './dataColorThemesLogic'

export function DataColorThemes(): JSX.Element {
    const { themes: _themes, themesLoading, defaultTheme } = useValues(dataColorThemesLogic)
    const { selectTheme } = useActions(dataColorThemesLogic)

    const { currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const themes = _themes || []

    return (
        <PayGateMini feature={AvailableFeature.DATA_COLOR_THEMES}>
            <div className="deprecated-space-y-4">
                <p>
                    These themes can be used in insights. You can also set a default theme for all insights below. For
                    more details, check out our{' '}
                    <Link
                        to="https://posthog.com/docs/product-analytics/color-themes?utm_campaign=settings&utm_medium=in-product"
                        target="_blank"
                    >
                        docs
                    </Link>
                    .
                </p>
                <LemonTable
                    loading={themesLoading}
                    dataSource={themes}
                    columns={[
                        {
                            title: 'Name',
                            dataIndex: 'name',
                            key: 'name',
                            render: (name, theme) => (
                                <LemonTableLink onClick={() => selectTheme(theme.id)} title={name as string} />
                            ),
                        },
                        {
                            title: 'Official',
                            dataIndex: 'is_global',
                            key: 'is_global',
                            render: (is_global) => (is_global ? <IconBadge className="text-success text-xl" /> : null),
                        },
                    ]}
                />
                <LemonButton type="secondary" onClick={() => selectTheme('new')}>
                    Add theme
                </LemonButton>

                <LemonLabel id="default_theme">Default theme</LemonLabel>
                <LemonSelect
                    value={defaultTheme?.id || null}
                    onChange={(value) => {
                        const theme = themes.find((theme) => theme.id === value)
                        LemonDialog.open({
                            title: `Change the default data theme to "${theme!.name}"?`,
                            description: 'This changes the default colors used when visualizing data in insights.',
                            primaryButton: {
                                children: 'Change default theme',
                                onClick: () => updateCurrentTeam({ default_data_theme: value! }),
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
        </PayGateMini>
    )
}
