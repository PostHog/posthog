import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { EditWidgetModalTileDetailsSection } from '../EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from '../registry'
import { editSurveyResultsWidgetModalLogic } from './editSurveyResultsWidgetModalLogic'
import { SURVEY_RESULTS_WIDGET_DATE_RANGE_OPTIONS } from './surveysWidgetConfigValidation'

function EditSurveyResultsWidgetModalContents(): JSX.Element {
    const {
        limit,
        dateFrom,
        tileName,
        tileDescription,
        activeFieldErrors,
        saving,
        saveDisabledReason,
        onClose,
        defaultTitle,
    } = useValues(editSurveyResultsWidgetModalLogic)
    const { setLimit, setDateFrom, setTileName, setTileDescription, clearFieldError, submit } = useActions(
        editSurveyResultsWidgetModalLogic
    )

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Widget settings"
            description="Configure the tile details. Pick which survey to show from the tile's filter bar."
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
                    <h5 className="text-sm font-semibold m-0">{getDashboardWidgetGroupLabel('surveys')}</h5>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <LemonField.Pure
                            label="Date range"
                            help="Scopes both the performance stats and the recent responses."
                        >
                            <LemonSelect
                                value={dateFrom}
                                disabled={saving}
                                options={SURVEY_RESULTS_WIDGET_DATE_RANGE_OPTIONS}
                                onChange={(value) => {
                                    if (value) {
                                        setDateFrom(value)
                                    }
                                }}
                                fullWidth
                            />
                        </LemonField.Pure>
                        <LemonField.Pure
                            label="Number of responses"
                            help="Show up to 25 recent responses on the tile."
                            error={activeFieldErrors.limit}
                        >
                            <LemonInput
                                type="number"
                                min={1}
                                max={25}
                                fullWidth
                                value={limit}
                                onChange={(value) => {
                                    setLimit(Number(value))
                                    clearFieldError('limit')
                                }}
                            />
                        </LemonField.Pure>
                    </div>
                </section>
            </div>
        </LemonModal>
    )
}

export function EditSurveyResultsWidgetModal({
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
            logic={editSurveyResultsWidgetModalLogic}
            props={{ onClose, config, onSave, name, defaultTitle, description }}
        >
            <EditSurveyResultsWidgetModalContents />
        </BindLogic>
    )
}
