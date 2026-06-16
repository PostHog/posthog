import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { EditWidgetModalTileDetailsSection } from '../EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from '../registry'
import { editExperimentResultsWidgetModalLogic } from './editExperimentResultsWidgetModalLogic'
import { ExperimentPickerSelect } from './ExperimentPickerSelect'

function EditExperimentResultsWidgetModalContents(): JSX.Element {
    const {
        experimentId,
        tileName,
        tileDescription,
        activeFieldErrors,
        saving,
        saveDisabledReason,
        onClose,
        defaultTitle,
    } = useValues(editExperimentResultsWidgetModalLogic)
    const { setExperimentId, setTileName, setTileDescription, clearFieldError, submit } = useActions(
        editExperimentResultsWidgetModalLogic
    )

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Widget settings"
            description="Configure tile details and which experiment's results appear on this dashboard."
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
                    <h5 className="text-sm font-semibold m-0">{getDashboardWidgetGroupLabel('experiments')}</h5>
                    <LemonField.Pure
                        label="Experiment"
                        help="Primary metric results for this experiment are shown on the tile."
                        error={activeFieldErrors.experimentId}
                    >
                        <ExperimentPickerSelect
                            pickerKey="results-modal"
                            value={experimentId}
                            size="medium"
                            fullWidth
                            onChange={(value) => {
                                setExperimentId(value)
                                clearFieldError('experimentId')
                            }}
                            dataAttr="experiment-results-widget-experiment-select"
                        />
                    </LemonField.Pure>
                </section>
            </div>
        </LemonModal>
    )
}

export function EditExperimentResultsWidgetModal({
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
            logic={editExperimentResultsWidgetModalLogic}
            props={{ onClose, config, onSave, name, defaultTitle, description }}
        >
            <EditExperimentResultsWidgetModalContents />
        </BindLogic>
    )
}
