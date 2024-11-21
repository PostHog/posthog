import { LemonTable } from '@posthog/lemon-ui'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'

export function DataColorThemeModal(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    return (
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
    )
}
