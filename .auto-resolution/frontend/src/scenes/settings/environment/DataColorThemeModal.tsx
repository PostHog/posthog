import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCopy, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonColorGlyph, LemonInput, LemonLabel, LemonModal, LemonTable } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { dataColorThemesModalLogic } from './dataColorThemeModalLogic'

export function DataColorThemeModal(): JSX.Element {
    const { theme, themeChanged, isOpen } = useValues(dataColorThemesModalLogic)
    const { submitTheme, closeModal, addColor, duplicateColor, removeColor } = useActions(dataColorThemesModalLogic)

    const isNew = theme?.id == null
    const isOfficial = theme?.is_global
    const title = isOfficial ? 'Official theme' : isNew ? 'Add theme' : 'Edit theme'

    return (
        <LemonModal
            title={title}
            onClose={closeModal}
            isOpen={isOpen}
            width={768}
            footer={
                isOfficial ? (
                    <div className="flex justify-between items-center w-full">
                        <span className="italic text-secondary">Official themes can't be edited.</span>
                        <LemonButton type="secondary" onClick={closeModal}>
                            Close
                        </LemonButton>
                    </div>
                ) : (
                    <LemonButton type="primary" onClick={submitTheme}>
                        Save
                    </LemonButton>
                )
            }
            hasUnsavedInput={themeChanged}
        >
            <Form logic={dataColorThemesModalLogic} formKey="theme" className="flex flex-col gap-2">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="My custom theme" autoFocus={isNew} disabled={isOfficial} />
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
                            render: (_, { color }) => <LemonColorGlyph color={color} />,
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
                            render: (_, { index }) => (
                                <LemonField key={index} name={['colors', index]}>
                                    <LemonInput className="max-w-20 font-mono" disabled={isOfficial} />
                                </LemonField>
                            ),
                        },
                        {
                            title: '',
                            key: 'actions',
                            width: 24,
                            render: (_, { index }) =>
                                isOfficial ? null : (
                                    <div className="flex">
                                        <LemonButton onClick={() => duplicateColor(index)}>
                                            <IconCopy className="text-lg" />
                                        </LemonButton>
                                        <LemonButton onClick={() => removeColor(index)}>
                                            <IconTrash className="text-danger text-lg" />
                                        </LemonButton>
                                    </div>
                                ),
                        },
                    ]}
                />
                {!isOfficial && (
                    <LemonButton
                        type="secondary"
                        className="self-start"
                        onClick={addColor}
                        icon={<IconPlus className="text-lg" />}
                    >
                        Add color
                    </LemonButton>
                )}
            </Form>
        </LemonModal>
    )
}
