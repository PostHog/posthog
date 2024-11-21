import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTextArea } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { dataColorThemesModalLogic } from './dataColorThemeModalLogic'

export function DataColorThemeModal(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { theme } = useValues(dataColorThemesModalLogic)

    const title = theme?.id == null ? 'Add theme' : 'Edit theme'
    const closeModal = () => {}

    return (
        <LemonModal
            title={title}
            onClose={closeModal}
            isOpen={theme != null}
            width={768}
            footer={<LemonButton type="primary">Save</LemonButton>}
        >
            <Form logic={dataColorThemesModalLogic} formKey="theme" className="flex flex-col gap-2">
                <LemonField name="name" label="Name">
                    {({ value, onChange }) => <LemonInput value={value} onChange={onChange} />}
                </LemonField>

                <LemonField name="description" label="Description">
                    {({ value, onChange }) => <LemonTextArea value={value} onChange={onChange} />}
                </LemonField>

                <LemonField name="colors" label="Colors">
                    <LemonTable
                        // loading={themesLoading}
                        dataSource={theme?.colors.map((color, index) => ({
                            name: `preset-${index + 1}`,
                            color,
                        }))}
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
                </LemonField>
                <LemonButton type="secondary" className="self-start">
                    Add color
                </LemonButton>
            </Form>
        </LemonModal>
    )
}
