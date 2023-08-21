import { Meta } from '@storybook/react'

import { EditableField as EditableFieldComponent } from './EditableField'
import { PageHeader } from '../PageHeader'
import { useState } from 'react'

const meta: Meta<typeof EditableFieldComponent> = {
    title: 'Components/Editable Field',
    component: EditableFieldComponent,
}
export default meta

export function EditableField_(): JSX.Element {
    const [savedTitle, setSavedTitle] = useState('Foo')
    const [savedDescription, setSavedDescription] = useState('Lorem ipsum dolor sit amet.')

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
