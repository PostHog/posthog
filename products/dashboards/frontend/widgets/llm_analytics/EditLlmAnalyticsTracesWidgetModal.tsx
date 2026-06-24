import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import { EditWidgetModalFiltersSubsection } from '../EditWidgetModalFiltersSection'
import { EditWidgetModalTileDetailsSection } from '../EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from '../registry'
import { editLlmAnalyticsTracesWidgetModalLogic } from './editLlmAnalyticsTracesWidgetModalLogic'

function EditLlmAnalyticsTracesWidgetModalContents(): JSX.Element {
    const {
        limit,
        dateFrom,
        tileName,
        tileDescription,
        filterTestAccounts,
        filterSupportTraces,
        appliedSavedFilterId,
        savedFilterOptions,
        activeFieldErrors,
        saving,
        saveDisabledReason,
        onClose,
        defaultTitle,
    } = useValues(editLlmAnalyticsTracesWidgetModalLogic)
    const {
        setLimit,
        setDateFrom,
        setTileName,
        setTileDescription,
        setFilterTestAccounts,
        setFilterSupportTraces,
        applySavedFilter,
        clearFieldError,
        submit,
    } = useActions(editLlmAnalyticsTracesWidgetModalLogic)

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Widget settings"
            description="Configure tile details and which traces appear on this dashboard."
            width={680}
            footer={
                <>
                    <div className="flex-1" />
                    <LemonButton type="secondary" onClick={onClose} disabled={saving}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={saving}
                        disabledReason={saveDisabledReason}
                        onClick={() => submit()}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <EditWidgetModalTileDetailsSection
                    tileName={tileName}
                    tileDescription={tileDescription}
                    defaultTitle={defaultTitle}
                    saving={saving}
                    setTileName={setTileName}
                    setTileDescription={setTileDescription}
                />
                <LemonDivider className="my-0" />
                <section className="flex flex-col gap-3">
                    <h5 className="text-sm font-semibold m-0">{getDashboardWidgetGroupLabel('llm_analytics')}</h5>
                    {savedFilterOptions.length > 0 ? (
                        <LemonField.Pure
                            label="Pre-fill from a saved filter"
                            help="Copies the saved Traces filter's date range and toggles into this tile. You can adjust them afterwards."
                        >
                            <LemonSelect
                                placeholder="Select a saved filter…"
                                value={appliedSavedFilterId}
                                options={savedFilterOptions}
                                disabledReason={saving ? 'Saving…' : undefined}
                                onChange={(value) => {
                                    if (value) {
                                        applySavedFilter(value)
                                    }
                                }}
                            />
                        </LemonField.Pure>
                    ) : null}
                    <div className="flex flex-col gap-4">
                        <EditWidgetModalFiltersSubsection
                            title="Trace filters"
                            filterTestAccounts={filterTestAccounts}
                            saving={saving}
                            setFilterTestAccounts={setFilterTestAccounts}
                        >
                            {/* Unlike sibling widgets (date range lives only on the tile bar), we surface it
                                here too so the saved-filter pre-fill has a visible target to write into. */}
                            <LemonField.Pure label="Date range">
                                <LemonSelect
                                    value={dateFrom}
                                    options={WIDGET_DATE_RANGE_SELECT_OPTIONS}
                                    disabledReason={saving ? 'Saving…' : undefined}
                                    onChange={(value) => {
                                        if (value) {
                                            setDateFrom(value as WidgetDateFromValue)
                                        }
                                    }}
                                />
                            </LemonField.Pure>
                            <LemonField.Pure
                                label="Number of traces"
                                help="Show up to 25 traces on the tile."
                                error={activeFieldErrors.limit}
                            >
                                <LemonInput
                                    type="number"
                                    min={1}
                                    max={25}
                                    fullWidth
                                    value={limit}
                                    onChange={(value) => {
                                        // Empty input yields NaN (valueAsNumber); keep the last valid
                                        // limit so Save doesn't lock behind a cryptic "received nan".
                                        const next = Number(value)
                                        setLimit(Number.isNaN(next) ? limit : next)
                                        clearFieldError('limit')
                                    }}
                                />
                            </LemonField.Pure>
                            <div className="sm:col-span-2">
                                <LemonSwitch
                                    checked={filterSupportTraces}
                                    onChange={setFilterSupportTraces}
                                    disabledReason={saving ? 'Saving…' : undefined}
                                    label="Hide support traces"
                                    bordered
                                />
                            </div>
                        </EditWidgetModalFiltersSubsection>
                    </div>
                </section>
            </div>
        </LemonModal>
    )
}

export function EditLlmAnalyticsTracesWidgetModal({
    isOpen,
    onClose,
    config,
    onSave,
    name,
    defaultTitle,
    description,
}: DashboardWidgetEditModalProps): JSX.Element | null {
    if (!isOpen) {
        return null
    }

    return (
        <BindLogic
            logic={editLlmAnalyticsTracesWidgetModalLogic}
            props={{ onClose, config, onSave, name, defaultTitle, description }}
        >
            <EditLlmAnalyticsTracesWidgetModalContents />
        </BindLogic>
    )
}
