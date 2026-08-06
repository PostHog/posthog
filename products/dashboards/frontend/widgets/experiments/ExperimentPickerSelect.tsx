import './ExperimentPickerSelect.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, type LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { fullName } from 'lib/utils/strings'

import type { ExperimentBasicApi } from 'products/experiments/frontend/generated/api.schemas'

import { experimentPickerLogic } from './experimentPickerLogic'

export type ExperimentPickerSelectProps = {
    /** Isolates picker state per mount (modal vs. each tile). */
    pickerKey: string
    value: number | null
    onChange: (experimentId: number | null) => void
    disabled?: boolean
    size?: 'small' | 'medium'
    fullWidth?: boolean
    dataAttr?: string
}

function ExperimentOptionLabel({ experiment }: { experiment: ExperimentBasicApi }): JSX.Element {
    const creator = experiment.created_by
    const creatorName = creator ? fullName(creator) || creator.email : null
    return (
        <span className="flex w-full items-center justify-between gap-2">
            <span className="min-w-0 flex-1 truncate">{experiment.name}</span>
            {creator ? (
                <span className="inline-flex shrink-0 items-center gap-1 text-xs text-muted">
                    <ProfilePicture
                        user={{ first_name: creator.first_name, last_name: creator.last_name, email: creator.email }}
                        size="sm"
                    />
                    <span className="max-w-32 truncate">{creatorName}</span>
                </span>
            ) : null}
        </span>
    )
}

export function ExperimentPickerSelect({
    pickerKey,
    value,
    onChange,
    disabled,
    size = 'small',
    fullWidth = false,
    dataAttr,
}: ExperimentPickerSelectProps): JSX.Element {
    const logic = experimentPickerLogic({ pickerKey })
    const { experimentOptions, experimentOptionsLoading, selectedExperiment, search } = useValues(logic)
    const { ensureOptionsLoaded, setSearch, ensureSelectedLoaded } = useActions(logic)

    // Resolve the selected label even when it falls outside the loaded/searched page.
    useEffect(() => {
        if (value != null) {
            ensureSelectedLoaded(value)
        }
    }, [value, ensureSelectedLoaded])

    const options = useMemo((): LemonInputSelectOption[] => {
        const byId = new Map<number, ExperimentBasicApi>()
        if (selectedExperiment) {
            byId.set(selectedExperiment.id, selectedExperiment)
        }
        for (const experiment of experimentOptions) {
            byId.set(experiment.id, experiment)
        }
        return Array.from(byId.values(), (experiment) => ({
            key: String(experiment.id),
            label: experiment.name,
            labelComponent: <ExperimentOptionLabel experiment={experiment} />,
        }))
    }, [experimentOptions, selectedExperiment])

    return (
        <LemonInputSelect
            mode="single"
            size={size}
            fullWidth={fullWidth}
            popoverClassName="ExperimentPickerSelect__dropdown"
            placeholder="Select an experiment"
            loading={experimentOptionsLoading}
            disabled={disabled}
            disableFiltering
            value={value != null ? [String(value)] : []}
            options={options}
            emptyStateComponent={
                <p className="text-secondary italic p-1">
                    {search ? `No experiments matching "${search}"` : 'No experiments yet'}
                </p>
            }
            onFocus={() => ensureOptionsLoaded()}
            onInputChange={(text) => setSearch(text)}
            onChange={(values) => onChange(values.length > 0 ? Number(values[0]) : null)}
            data-attr={dataAttr}
        />
    )
}
