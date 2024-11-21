import { LemonButton, LemonInput, LemonSelect, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { dataColorThemesConfigLogic } from './dataColorThemesConfigLogic'

export function DataColorThemes(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const { themes, selectedTheme, themesLoading } = useValues(dataColorThemesConfigLogic)
    const { selectTheme } = useActions(dataColorThemesConfigLogic)

    return (
        <div className="space-y-4">
            <div className="flex gap-2">
                <LemonSelect
                    loading={themesLoading}
                    size="small"
                    options={themes != null ? themes.map(({ name, id }) => ({ label: name, value: id })) : []}
                    data-attr="data-color-theme-select"
                    value={selectedTheme?.id}
                    onChange={selectTheme}
                />
                <LemonButton size="small" type="secondary">
                    Add theme
                </LemonButton>
            </div>
            <LemonTable
                loading={themesLoading}
                dataSource={selectedTheme?.colors.map((color, index) => ({ name: `preset-${index + 1}`, color }))}
                columns={[
                    {
                        title: '',
                        dataIndex: 'color',
                        key: 'glyph',
                        render: (_, { color }) => {
                            return (
                                <SeriesGlyph
                                    style={{
                                        borderColor: color,
                                        color: color,
                                        backgroundColor: isDarkModeOn
                                            ? RGBToRGBA(lightenDarkenColor(color, -20), 0.3)
                                            : hexToRGBA(color, 0.2),
                                    }}
                                />
                            )
                        },
                        width: 24,
                    },
                    {
                        title: 'Name',
                        dataIndex: 'name',
                        key: 'name',
                    },
                    {
                        title: 'Color',
                        dataIndex: 'color',
                        render: (_, { color }) => {
                            return <LemonInput value={color} className="max-w-20 font-mono" />
                        },
                    },
                    {
                        title: '',
                        key: 'actions',
                        width: 24,
                    },
                ]}
                footer={
                    <div className="px-3 py-2">
                        <LemonButton type="secondary">Add color</LemonButton>
                    </div>
                }
            />
            <LemonButton type="primary">Save</LemonButton>
        </div>
    )
}
