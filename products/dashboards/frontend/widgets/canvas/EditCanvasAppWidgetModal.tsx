import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { EditWidgetModalTileDetailsSection } from '../EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from '../registry'
import { CanvasPickerSelect } from './CanvasPickerSelect'
import { editCanvasAppWidgetModalLogic } from './editCanvasAppWidgetModalLogic'

function EditCanvasAppWidgetModalContents(): JSX.Element {
    const {
        canvasId,
        tileName,
        tileDescription,
        activeFieldErrors,
        saving,
        saveDisabledReason,
        onClose,
        defaultTitle,
    } = useValues(editCanvasAppWidgetModalLogic)
    const { setCanvasId, setTileName, setTileDescription, clearFieldError, submit } =
        useActions(editCanvasAppWidgetModalLogic)

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Widget settings"
            description="Pick the canvas to show on this tile. Each viewer sees it with their own permissions."
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
                    <h5 className="text-sm font-semibold m-0">{getDashboardWidgetGroupLabel('canvas')}</h5>
                    <LemonField.Pure
                        label="Canvas"
                        help="Only canvases you can see are listed. Viewers who cannot see the canvas get a placeholder."
                        error={activeFieldErrors.canvasId}
                    >
                        <CanvasPickerSelect
                            pickerKey="edit-canvas-app-widget-modal"
                            value={canvasId}
                            disabled={saving}
                            size="medium"
                            fullWidth
                            onChange={(value) => {
                                setCanvasId(value)
                                clearFieldError('canvasId')
                            }}
                            dataAttr="edit-canvas-app-widget-canvas"
                        />
                    </LemonField.Pure>
                </section>
            </div>
        </LemonModal>
    )
}

export function EditCanvasAppWidgetModal({
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
            logic={editCanvasAppWidgetModalLogic}
            props={{ onClose, config, onSave, name, defaultTitle, description }}
        >
            <EditCanvasAppWidgetModalContents />
        </BindLogic>
    )
}
