import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { ColorGlyph } from 'lib/components/SeriesGlyph'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { dataColorThemesModalLogic } from './dataColorThemeModalLogic'

export function DataColorThemeModal(): JSX.Element {
    const { theme } = useValues(dataColorThemesModalLogic)
    const { submitTheme } = useActions(dataColorThemesModalLogic)

    const isNew = theme?.id == null
    const title = isNew ? 'Add theme' : 'Edit theme'
    const closeModal = () => {}

    return (
        <LemonModal
            title={title}
            onClose={closeModal}
            isOpen={theme != null}
            width={768}
            footer={
                <LemonButton type="primary" onClick={submitTheme}>
                    Save
                </LemonButton>
            }
        >
            <Form logic={dataColorThemesModalLogic} formKey="theme" className="flex flex-col gap-2">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="My custom theme" autoFocus={isNew} />
                </LemonField>

                <LemonLabel>Colors</LemonLabel>
                <LemonTable
                    dataSource={theme?.colors?.map((color, index) => ({
                        name: `preset-${index + 1}`,
                        color,
                        index,
                    }))}
                    columns={[
                        {
                            title: '',
                            dataIndex: 'color',
                            key: 'glyph',
                            render: (_, { color }) => <ColorGlyph color={color} />,
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
                            render: (_, { index }) => {
                                return (
                                    <LemonField key={index} name={['colors', index]}>
                                        <LemonInput className="max-w-20 font-mono" />
                                    </LemonField>
                                )
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
            </Form>
        </LemonModal>
    )
}
