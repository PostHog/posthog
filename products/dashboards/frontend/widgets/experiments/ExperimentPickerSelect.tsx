import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, type LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { fullName } from 'lib/utils'
import { urls } from 'scenes/urls'

import type { ExperimentApi } from 'products/experiments/frontend/generated/api.schemas'

import { experimentPickerLogic } from './experimentPickerLogic'

function ExperimentOptionLabel({ experiment }: { experiment: ExperimentApi }): JSX.Element {
    const creator = experiment.created_by
    const creatorName = creator ? fullName(creator) || creator.email : null
    return (
        <span className="inline-flex items-center gap-2">
            <span className="truncate">{experiment.name}</span>
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
        const byId = new Map<number, ExperimentApi>()
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
            placeholder="Select an experiment"
            loading={experimentOptionsLoading}
            disabled={disabled}
            disableFiltering
            value={value != null ? [String(value)] : []}
            options={options}
            emptyStateComponent={
                search ? (
                    <p className="text-secondary italic p-1">No experiments matching "{search}"</p>
                ) : (
                    <div className="flex flex-col gap-1 p-1 text-secondary">
                        <span>No experiments yet.</span>
                        <Link to={urls.experiment('new')} target="_blank">
                            Create an experiment
                        </Link>
                    </div>
                )
            }
            onFocus={() => ensureOptionsLoaded()}
            onInputChange={(text) => setSearch(text)}
            onChange={(values) => onChange(values.length > 0 ? Number(values[0]) : null)}
            data-attr={dataAttr}
        />
    )
}
