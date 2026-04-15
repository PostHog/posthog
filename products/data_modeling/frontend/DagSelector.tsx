import { useValues } from 'kea'

import { LemonDialog, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { dataModelingLogic } from 'scenes/data-warehouse/scene/dataModelingLogic'

import { DataModelingSyncInterval } from '~/types'

const CREATE_NEW_DAG_VALUE = '__create_new__'

const SYNC_FREQUENCY_OPTIONS: { value: DataModelingSyncInterval; label: string }[] = [
    { value: '15min', label: '15 minutes' },
    { value: '30min', label: '30 minutes' },
    { value: '1hour', label: '1 hour' },
    { value: '6hour', label: '6 hours' },
    { value: '12hour', label: '12 hours' },
    { value: '24hour', label: 'Daily' },
    { value: '7day', label: 'Weekly' },
    { value: '30day', label: 'Monthly' },
]

export function openCreateDagDialog({
    existingNames,
    onSubmit,
}: {
    existingNames: Set<string>
    onSubmit: (dag: { name: string; description: string; sync_frequency: DataModelingSyncInterval }) => void
}): void {
    LemonDialog.openForm({
        title: 'New DAG',
        initialValues: {
            dagName: '',
            dagDescription: '',
            syncFrequency: '24hour' as DataModelingSyncInterval,
        },
        content: (
            <>
                <LemonField name="dagName" label="Name">
                    <LemonInput placeholder="Enter a DAG name" autoFocus />
                </LemonField>
                <LemonField name="dagDescription" label="Description" className="mt-2">
                    <LemonInput placeholder="Optional description" />
                </LemonField>
                <LemonField name="syncFrequency" label="Sync frequency" className="mt-2">
                    {({ value, onChange }) => (
                        <LemonSelect value={value} onChange={onChange} options={SYNC_FREQUENCY_OPTIONS} fullWidth />
                    )}
                </LemonField>
            </>
        ),
        errors: {
            dagName: (name) => {
                if (!name?.trim()) {
                    return 'You must enter a DAG name'
                }
                if (existingNames.has(name.trim())) {
                    return 'A DAG with this name already exists'
                }
                return undefined
            },
        },
        onSubmit: ({ dagName, dagDescription, syncFrequency }) => {
            onSubmit({
                name: dagName.trim(),
                description: dagDescription?.trim() ?? '',
                sync_frequency: syncFrequency,
            })
        },
    })
}

export function DagSelector({
    selectedDagId,
    onSelectDag,
    onCreateDag,
}: {
    selectedDagId: string | null
    onSelectDag: (dagId: string | null) => void
    onCreateDag: (onSelect: (newDagId: string) => void) => void
}): JSX.Element {
    const { dags } = useValues(dataModelingLogic)
    const options = [
        ...dags.map((d) => ({ value: d.id, label: d.name })),
        { value: CREATE_NEW_DAG_VALUE, label: '+ Create new DAG' },
    ]

    const handleSelectChange = (selected: string | null): void => {
        if (selected === CREATE_NEW_DAG_VALUE) {
            onCreateDag(onSelectDag)
        } else {
            onSelectDag(selected)
        }
    }

    return (
        <LemonSelect
            value={selectedDagId}
            onChange={handleSelectChange}
            options={options}
            placeholder="Select a DAG"
            fullWidth
        />
    )
}
