import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { EditableField as EditableFieldComponent } from './EditableField'
import { PageHeader } from '../PageHeader'

export default {
    title: 'Forms/Editable Field',
    component: EditableFieldComponent,
} as ComponentMeta<typeof EditableFieldComponent>

export function EditableField_(): JSX.Element {
    const [savedTitle, setSavedTitle] = React.useState('Foo')
    const [savedDescription, setSavedDescription] = React.useState('Lorem ipsum dolor sit amet.')

    return (
        <PageHeader
            title={<EditableFieldComponent name="title" value={savedTitle} onSave={(value) => setSavedTitle(value)} />}
            caption={
                <EditableFieldComponent
                    name="description"
                    value={savedDescription}
                    onSave={(value) => setSavedDescription(value)}
                    multiline
                />
            }
        />
    )
}
