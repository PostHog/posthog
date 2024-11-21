import { LemonButton, LemonInput, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { dataColorThemesConfigLogic } from './dataColorThemesConfigLogic'

export function DataColorThemeModal(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { selectedTheme } = useValues(dataColorThemesConfigLogic)

    const title = selectedTheme?.id == null ? 'Add theme' : 'Edit theme'
    const closeModal = () => {}

    return (
        <LemonModal
            title={title}
            onClose={closeModal}
            isOpen={selectedTheme != null}
            width={768}
            footer={<LemonButton type="primary">Save</LemonButton>}
        >
            <div className="flex flex-col gap-2">
                <LemonTable
                    // loading={themesLoading}
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
                />
                <LemonButton type="secondary" className="self-start">
                    Add color
                </LemonButton>
            </div>
        </LemonModal>
    )
}
