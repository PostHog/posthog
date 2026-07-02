import './SurveyPickerSelect.scss'

import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlus } from '@posthog/icons'

import { LemonInputSelect, type LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect'
import { urls } from 'scenes/urls'

import type { SurveyApi } from 'products/surveys/frontend/generated/api.schemas'

import { surveyPickerLogic } from './surveyPickerLogic'

export type SurveyPickerSelectProps = {
    /** Isolates picker state per mount (modal vs. each tile). */
    pickerKey: string
    value: string | null
    onChange: (surveyId: string | null) => void
    disabled?: boolean
    size?: 'small' | 'medium'
    fullWidth?: boolean
    dataAttr?: string
    /** Fired when the "New survey" action is clicked, before opening the create page — used for adoption tracking. */
    onCreateNew?: () => void
}

function surveyStatusLabel(survey: SurveyApi): string {
    if (survey.archived) {
        return 'Archived'
    }
    if (!survey.start_date) {
        return 'Draft'
    }
    return survey.end_date ? 'Ended' : 'Active'
}

function SurveyOptionLabel({ survey }: { survey: SurveyApi }): JSX.Element {
    return (
        <span className="flex w-full items-center justify-between gap-2">
            <span className="min-w-0 flex-1 truncate">{survey.name}</span>
            <span className="shrink-0 text-xs text-muted">{surveyStatusLabel(survey)}</span>
        </span>
    )
}

export function SurveyPickerSelect({
    pickerKey,
    value,
    onChange,
    disabled,
    size = 'small',
    fullWidth = false,
    dataAttr,
    onCreateNew,
}: SurveyPickerSelectProps): JSX.Element {
    // ensureSurveyId lets the logic resolve the selected label itself (even when it's outside the
    // loaded/searched page), so we don't need a component effect to trigger the fetch.
    const logic = surveyPickerLogic({ pickerKey, ensureSurveyId: value })
    const { surveyOptions, surveyOptionsLoading, selectedSurvey, search } = useValues(logic)
    const { ensureOptionsLoaded, setSearch } = useActions(logic)

    const options = useMemo((): LemonInputSelectOption[] => {
        const byId = new Map<string, SurveyApi>()
        if (selectedSurvey) {
            byId.set(selectedSurvey.id, selectedSurvey)
        }
        for (const survey of surveyOptions) {
            byId.set(survey.id, survey)
        }
        return Array.from(byId.values(), (survey) => ({
            key: survey.id,
            label: survey.name,
            labelComponent: <SurveyOptionLabel survey={survey} />,
        }))
    }, [surveyOptions, selectedSurvey])

    return (
        <LemonInputSelect
            mode="single"
            size={size}
            fullWidth={fullWidth}
            popoverClassName="SurveyPickerSelect__dropdown"
            placeholder="Select a survey"
            loading={surveyOptionsLoading}
            disabled={disabled}
            disableFiltering
            value={value != null ? [value] : []}
            options={options}
            emptyStateComponent={
                <p className="text-secondary italic p-1">
                    {search ? `No surveys matching "${search}"` : 'No surveys yet'}
                </p>
            }
            onFocus={() => ensureOptionsLoaded()}
            onInputChange={(text) => setSearch(text)}
            onChange={(values) => onChange(values.length > 0 ? values[0] : null)}
            action={{
                // Open the create flow in a new tab so the dashboard (and this tile's selection) is kept.
                onClick: () => {
                    onCreateNew?.()
                    window.open(urls.survey('new'), '_blank', 'noopener,noreferrer')
                },
                children: (
                    <span className="flex items-center gap-1">
                        <IconPlus /> New survey
                    </span>
                ),
            }}
            data-attr={dataAttr}
        />
    )
}
