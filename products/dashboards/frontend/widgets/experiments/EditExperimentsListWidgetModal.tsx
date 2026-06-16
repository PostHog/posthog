import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { EditWidgetModalTileDetailsSection } from '../EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from '../registry'
import { editExperimentsListWidgetModalLogic } from './editExperimentsListWidgetModalLogic'

function EditExperimentsListWidgetModalContents(): JSX.Element {
    const { limit, tileName, tileDescription, activeFieldErrors, saving, saveDisabledReason, onClose, defaultTitle } =
        useValues(editExperimentsListWidgetModalLogic)
    const { setLimit, setTileName, setTileDescription, clearFieldError, submit } = useActions(
        editExperimentsListWidgetModalLogic
    )

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Widget settings"
            description="Configure tile details and which experiments appear on this dashboard."
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
                    <p className="m-0 text-xs text-muted">
                        Filter by status and creator directly on the tile using the filter bar.
                    </p>
                    <LemonField.Pure
                        label="Number of experiments"
                        help="Show up to 25 experiments on the tile."
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
                </section>
            </div>
        </LemonModal>
    )
}

export function EditExperimentsListWidgetModal({
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
            logic={editExperimentsListWidgetModalLogic}
            props={{ onClose, config, onSave, name, defaultTitle, description }}
        >
            <EditExperimentsListWidgetModalContents />
        </BindLogic>
    )
}
