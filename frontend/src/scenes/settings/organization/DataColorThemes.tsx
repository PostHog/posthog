import { LemonButton, LemonInput, LemonSelect, LemonTable } from '@posthog/lemon-ui'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'

export function DataColorThemes(): JSX.Element {
    const color = '#ff0000'
    const isDarkModeOn = false
    return (
        <div className="space-y-4">
            <LemonSelect
                options={[
                    {
                        label: 'Default',
                        value: 'default',
                    },
                ]}
                data-attr="data-color-theme-select"
            />
            <LemonTable
                dataSource={[{ name: 'preset-1', lightModeColor: '#ff0000', darkModeColor: '#ff0000' }]}
                columns={[
                    {
                        title: 'Name',
                        dataIndex: 'name',
                        key: 'name',
                    },
                    {
                        title: 'Default/light mode color',
                        dataIndex: 'lightModeColor',
                        render: (_, { lightModeColor }) => {
                            return (
                                <div className="flex gap-2">
                                    <SeriesGlyph
                                        style={{
                                            borderColor: color,
                                            color: color,
                                            backgroundColor: isDarkModeOn
                                                ? RGBToRGBA(lightenDarkenColor(color, -20), 0.3)
                                                : hexToRGBA(color, 0.2),
                                        }}
                                    />
                                    <LemonInput
                                        size="xsmall"
                                        value={lightModeColor}
                                        className="max-w-50 overflow-hidden"
                                        prefix={
                                            <div className="bg-border-light text-muted-3000 h-6 w-7 relative -left-1 flex items-center justify-center border-r">
                                                #
                                            </div>
                                        }
                                    />
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Dark mode color',
                        dataIndex: 'darkModeColor',
                    },
                    {
                        title: '',
                        key: 'actions',
                        width: 24,
                    },
                ]}
                footer={
                    <div className="px-3 py-2">
                        <LemonButton type="secondary" size="xsmall">
                            Add color
                        </LemonButton>
                    </div>
                }
            />
            <LemonButton type="primary">Add theme</LemonButton>
        </div>
    )
}
