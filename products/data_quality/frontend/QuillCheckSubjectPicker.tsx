import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Badge,
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Field,
    FieldLabel,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { subjectTypeLabel } from './checksConstants'
import { SelectableSubject, dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'

function subjectKey(subject: Pick<SelectableSubject, 'type' | 'id'>): string {
    return `${subject.type}:${subject.id}`
}

export function QuillCheckSubjectPicker(): JSX.Element {
    const { subject, selectableSubjects, checkSubjectsLoading, checkSubjectsError } =
        useValues(dataQualityCheckEditorLogic)
    const { setSubject, loadCheckSubjects } = useActions(dataQualityCheckEditorLogic)
    const inputId = useId()
    const subjectsByKey = new Map(selectableSubjects.map((candidate) => [subjectKey(candidate), candidate]))
    const catalogFailed = !!checkSubjectsError && !checkSubjectsLoading

    return (
        <div className="flex flex-col gap-2">
            <Field>
                <FieldLabel htmlFor={inputId}>Table, view, or metric</FieldLabel>
                <Combobox
                    items={[...subjectsByKey.keys()]}
                    value={subject ? `${subject.subjectType}:${subject.subjectId}` : null}
                    onValueChange={(key: string | null) => {
                        const selected = key ? subjectsByKey.get(key) : undefined
                        if (selected) {
                            setSubject({ subjectId: selected.id, subjectType: selected.type })
                        }
                    }}
                    itemToStringLabel={(key: string) => subjectsByKey.get(key)?.name ?? ''}
                >
                    <ComboboxInput
                        id={inputId}
                        placeholder={checkSubjectsLoading ? 'Loading...' : 'Search tables, views, and metrics'}
                        data-attr="data-quality-check-subject"
                    />
                    <ComboboxContent>
                        <ComboboxEmpty>
                            {checkSubjectsLoading ? 'Loading...' : 'No tables, views, or metrics match.'}
                        </ComboboxEmpty>
                        <ComboboxList>
                            {(key: string) => {
                                const candidate = subjectsByKey.get(key)
                                return (
                                    <ComboboxItem key={key} value={key}>
                                        <span className="min-w-0 truncate">{candidate?.name}</span>
                                        {candidate && (
                                            <Badge className="ms-auto">{subjectTypeLabel(candidate.type)}</Badge>
                                        )}
                                    </ComboboxItem>
                                )
                            }}
                        </ComboboxList>
                    </ComboboxContent>
                </Combobox>
            </Field>
            {catalogFailed && (
                <div className="flex flex-wrap items-center gap-2">
                    <Text size="xs" variant="muted" className="m-0">
                        Couldn't load what you can check.
                    </Text>
                    <Button variant="outline" onClick={loadCheckSubjects}>
                        Retry
                    </Button>
                </div>
            )}
            {!checkSubjectsLoading && selectableSubjects.length === 0 && (
                <Text size="xs" variant="muted" className="m-0">
                    <Button variant="link" size="inline" render={<LinkPrimitive to={urls.database()} />}>
                        Browse tables and views
                    </Button>{' '}
                    or{' '}
                    <Button variant="link" size="inline" render={<LinkPrimitive to={urls.metrics()} />}>
                        create a HogQL metric
                    </Button>{' '}
                    first.
                </Text>
            )}
        </div>
    )
}
