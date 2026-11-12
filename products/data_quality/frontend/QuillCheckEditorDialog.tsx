import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Spinner,
    Text,
    cn,
} from '@posthog/quill'

import { checkTypeLabel } from './checksConstants'
import { EMPTY_CHECK_FORM, dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { CheckTypeEnumApi } from './generated/api.schemas'
import { QuillCheckAdvancedOptions } from './QuillCheckAdvancedOptions'
import { QuillCheckConfigFields } from './QuillCheckConfigFields'
import { QuillCheckFormField } from './QuillCheckFormField'
import { QuillCheckSubjectPicker } from './QuillCheckSubjectPicker'
import { QuillConfirmDialog } from './QuillConfirmDialog'
import { QuillOptionCombobox } from './QuillOptionCombobox'

function RetryRow({ message, onRetry }: { message: string; onRetry: () => void }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <Text size="xs" variant="muted" className="m-0">
                {message}
            </Text>
            <Button variant="outline" onClick={onRetry}>
                Retry
            </Button>
        </div>
    )
}

function CheckTypeField(): JSX.Element {
    const { checkTypes, checkTypeByName } = useValues(dataQualityCheckEditorLogic)
    const { setCheckFormValues } = useActions(dataQualityCheckEditorLogic)
    const items = checkTypes.map((checkType) => ({
        value: checkType.check_type,
        label: checkTypeLabel(checkType.check_type),
    }))

    return (
        <QuillCheckFormField name="checkType" label="Check type">
            {({ id, value }) => (
                <div className="flex flex-col gap-1">
                    <Select
                        items={items}
                        value={value}
                        onValueChange={(checkType) => {
                            if (!checkType) {
                                return
                            }
                            setCheckFormValues({
                                checkType: checkType as CheckTypeEnumApi,
                                columnName: EMPTY_CHECK_FORM.columnName,
                                acceptedValues: EMPTY_CHECK_FORM.acceptedValues,
                                toSubjectUuid: EMPTY_CHECK_FORM.toSubjectUuid,
                                toColumn: EMPTY_CHECK_FORM.toColumn,
                                rowCountMin: EMPTY_CHECK_FORM.rowCountMin,
                                rowCountMax: EMPTY_CHECK_FORM.rowCountMax,
                                maxAgeMinutes: EMPTY_CHECK_FORM.maxAgeMinutes,
                                customSql: EMPTY_CHECK_FORM.customSql,
                            })
                        }}
                    >
                        <SelectTrigger id={id} data-attr="data-quality-check-type">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {items.map((item) => (
                                <SelectItem key={item.value} value={item.value}>
                                    {item.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    {checkTypeByName[value]?.description && (
                        <Text size="xs" variant="muted" className="m-0">
                            {checkTypeByName[value].description}
                        </Text>
                    )}
                </div>
            )}
        </QuillCheckFormField>
    )
}

function ColumnField(): JSX.Element {
    const { availableColumns, checkSubjectsLoading } = useValues(dataQualityCheckEditorLogic)

    return (
        <QuillCheckFormField name="columnName" label="Column">
            {({ id, value, onChange, invalid }) => (
                <QuillOptionCombobox
                    id={id}
                    invalid={invalid}
                    loading={checkSubjectsLoading && !availableColumns.length}
                    options={availableColumns.map((column) => ({ value: column, label: column }))}
                    value={value}
                    onChange={onChange}
                    placeholder="Search columns"
                    emptyText="No columns match."
                    dataAttr="data-quality-check-column"
                />
            )}
        </QuillCheckFormField>
    )
}

export function QuillCheckEditorDialog(): JSX.Element {
    const {
        isOpen,
        editingCheck,
        checkForm,
        checkFormChanged,
        checkTypes,
        checkTypesError,
        checkTypesLoading,
        requiresColumn,
        openedWithoutSubject,
        checkSubjectsLoading,
        checkSubjectsError,
        subject,
        isCheckFormSubmitting,
        serverError,
    } = useValues(dataQualityCheckEditorLogic)
    const { loadCheckTypes, loadCheckSubjects, closeEditor, submitCheckForm } = useActions(dataQualityCheckEditorLogic)
    const [confirmingDiscard, setConfirmingDiscard] = useState(false)

    const formShapeLoading = checkTypesLoading && !checkTypes.length
    const awaitingSubject = openedWithoutSubject && !subject
    const checkTypesFailedEmpty = checkTypesError && !checkTypesLoading && !checkTypes.length
    const catalogFailed = !!checkSubjectsError && !checkSubjectsLoading
    const saveDisabledReason = awaitingSubject
        ? 'Pick a table, view, or metric first'
        : formShapeLoading
          ? 'Loading the check types'
          : checkTypesFailedEmpty
            ? 'Load the check types to continue'
            : catalogFailed && !openedWithoutSubject
              ? 'Load the columns to continue'
              : undefined

    const requestClose = (): void => {
        if (checkFormChanged) {
            setConfirmingDiscard(true)
            return
        }
        closeEditor()
    }

    return (
        <>
            <Dialog
                open={isOpen}
                onOpenChange={(open: boolean) => {
                    if (!open) {
                        requestClose()
                    }
                }}
            >
                <DialogContent className="sm:max-w-160" data-attr="data-quality-check-editor">
                    <DialogHeader>
                        <DialogTitle>{editingCheck ? 'Edit check' : 'New check'}</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <div className="flex flex-col gap-4">
                            {formShapeLoading && (
                                <div className="flex items-center justify-center gap-2 py-8">
                                    <Spinner />
                                    <Text size="xs" variant="muted" render={<span />}>
                                        Loading check types...
                                    </Text>
                                </div>
                            )}
                            {openedWithoutSubject && <QuillCheckSubjectPicker />}
                            {catalogFailed && !openedWithoutSubject && (
                                <RetryRow
                                    message="Couldn't load the columns for this subject."
                                    onRetry={loadCheckSubjects}
                                />
                            )}
                            {checkTypesFailedEmpty && (
                                <RetryRow message="Couldn't load check types." onRetry={loadCheckTypes} />
                            )}
                            <Form
                                logic={dataQualityCheckEditorLogic}
                                formKey="checkForm"
                                className={cn(
                                    'flex flex-col gap-4',
                                    (formShapeLoading || awaitingSubject || checkTypesFailedEmpty) && 'hidden'
                                )}
                            >
                                <CheckTypeField />
                                {requiresColumn && <ColumnField />}
                                <QuillCheckConfigFields checkType={checkForm.checkType} />
                                <QuillCheckAdvancedOptions />
                            </Form>
                        </div>
                    </DialogBody>
                    <DialogFooter className="flex-wrap items-center">
                        {serverError && (
                            <Text size="xs" variant="destructive" className="m-0 me-auto">
                                {serverError}
                            </Text>
                        )}
                        <Button variant="outline" onClick={requestClose} data-attr="data-quality-check-cancel">
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            onClick={submitCheckForm}
                            loading={isCheckFormSubmitting}
                            disabledReason={saveDisabledReason}
                            data-attr="data-quality-check-save"
                        >
                            Save check
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
            <QuillConfirmDialog
                open={confirmingDiscard}
                title="Discard changes?"
                description="Your unsaved changes will be lost."
                confirmLabel="Discard changes"
                cancelLabel="Keep editing"
                onConfirm={() => {
                    setConfirmingDiscard(false)
                    closeEditor()
                }}
                onCancel={() => setConfirmingDiscard(false)}
                dataAttr="data-quality-discard-check"
            />
        </>
    )
}
