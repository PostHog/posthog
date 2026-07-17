import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { EditWidgetModalTileDetailsSection } from '../EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from '../registry'
import { editExperimentResultsWidgetModalLogic } from './editExperimentResultsWidgetModalLogic'

function EditExperimentResultsWidgetModalContents(): JSX.Element {
    const { tileName, tileDescription, saving, saveDisabledReason, onClose, defaultTitle } = useValues(
        editExperimentResultsWidgetModalLogic
    )
    const { setTileName, setTileDescription, submit } = useActions(editExperimentResultsWidgetModalLogic)

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Widget settings"
            description="Configure the tile details. Pick which experiment's results to show from the tile's filter bar."
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
            <EditWidgetModalTileDetailsSection
                tileName={tileName}
                tileDescription={tileDescription}
                defaultTitle={defaultTitle}
                saving={saving}
                setTileName={setTileName}
                setTileDescription={setTileDescription}
            />
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
