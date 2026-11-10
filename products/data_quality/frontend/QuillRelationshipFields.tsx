import { useActions, useValues } from 'kea'

import { dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { QuillCheckFormField } from './QuillCheckFormField'
import { QuillOptionCombobox } from './QuillOptionCombobox'

export function QuillRelationshipFields(): JSX.Element {
    const { checkForm, relationshipSubjects, checkSubjectsLoading } = useValues(dataQualityCheckEditorLogic)
    const { setCheckFormValues } = useActions(dataQualityCheckEditorLogic)

    const selected = relationshipSubjects.find((subject) => subject.id === checkForm.toSubjectUuid)

    return (
        <>
            <QuillCheckFormField name="toSubjectUuid" label="References table or view">
                {({ id, invalid }) => (
                    <QuillOptionCombobox
                        id={id}
                        invalid={invalid}
                        loading={checkSubjectsLoading}
                        options={relationshipSubjects.map((subject) => ({ value: subject.id, label: subject.name }))}
                        value={checkForm.toSubjectUuid}
                        onChange={(toSubjectUuid) =>
                            setCheckFormValues({
                                toSubjectUuid,
                                toSubjectType: relationshipSubjects.find((subject) => subject.id === toSubjectUuid)
                                    ?.type,
                                toColumn: '',
                                toLookbackHours: null,
                            })
                        }
                        placeholder="Search tables and views"
                        emptyText="No tables or views match."
                        dataAttr="data-quality-check-relationship-subject"
                    />
                )}
            </QuillCheckFormField>
            <QuillCheckFormField name="toColumn" label="References column">
                {({ id, value, onChange, invalid }) => (
                    <QuillOptionCombobox
                        id={id}
                        invalid={invalid}
                        disabled={!selected}
                        options={(selected?.fields ?? []).map((field) => ({ value: field, label: field }))}
                        value={value}
                        onChange={onChange}
                        placeholder={selected ? 'Search columns' : 'Pick a table or view first'}
                        emptyText="No columns match."
                        dataAttr="data-quality-check-relationship-column"
                    />
                )}
            </QuillCheckFormField>
        </>
    )
}
