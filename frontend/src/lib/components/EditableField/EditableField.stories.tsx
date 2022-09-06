import React, { useState } from 'react'
import { ComponentMeta } from '@storybook/react'

import { EditableField as EditableFieldComponent, EditableFieldProps } from './EditableField'
import { PageHeader } from '../PageHeader'

export default {
    title: 'Components/Editable Field',
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

function SelfCountainedEditableField(props: EditableFieldProps): JSX.Element {
    const [value, setValue] = useState(props.value)
    return <EditableFieldComponent {...props} value={value} onSave={(newValue) => setValue(newValue)} />
}

export function ControlledModes(): JSX.Element {
    return (
        <>
            <div className="border rounded flex flex-col gap-2 p-4">
                <div className="border rounded p-4">
                    <h5>uncontrolled</h5>
                    <SelfCountainedEditableField value="uncontrolled" name="uncontrolled" />
                </div>
                <div className="border rounded p-4">
                    <h5>controlled - view only (no edit)</h5>
                    <SelfCountainedEditableField value="controlled - only view" name="controlled-view" mode="view" />
                </div>
                <div className="border rounded p-4">
                    <h5>
                        controlled - edit only (no view, expects save and cancel to be handled externally for e.g. as
                        part of a form)
                    </h5>
                    <SelfCountainedEditableField value="controlled - only edit" name="controlled-edit" mode="edit" />
                </div>
            </div>
        </>
    )
}
