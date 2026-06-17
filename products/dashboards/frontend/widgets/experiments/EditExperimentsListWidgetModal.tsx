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
import { editExperimentsListWidgetModalLogic } from './editExperimentsListWidgetModalLogic'
import {
    EXPERIMENTS_WIDGET_ORDER_BY_OPTIONS,
    EXPERIMENTS_WIDGET_ORDER_DIRECTION_OPTIONS,
} from './experimentsWidgetConfigValidation'

function EditExperimentsListWidgetModalContents(): JSX.Element {
    const {
        limit,
        orderBy,
        orderDirection,
        tileName,
        tileDescription,
        activeFieldErrors,
        saving,
        saveDisabledReason,
        onClose,
        defaultTitle,
    } = useValues(editExperimentsListWidgetModalLogic)
    const { setLimit, setOrderBy, setOrderDirection, setTileName, setTileDescription, clearFieldError, submit } =
        useActions(editExperimentsListWidgetModalLogic)

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
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <LemonField.Pure label="Sort by" error={activeFieldErrors.orderBy}>
                            <LemonSelect
                                fullWidth
                                value={orderBy}
                                onChange={(value) => {
                                    if (value) {
                                        setOrderBy(value)
                                        clearFieldError('orderBy')
                                    }
                                }}
                                options={EXPERIMENTS_WIDGET_ORDER_BY_OPTIONS}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Direction" error={activeFieldErrors.orderDirection}>
                            <LemonSelect
                                fullWidth
                                value={orderDirection}
                                onChange={(value) => {
                                    if (value) {
                                        setOrderDirection(value)
                                        clearFieldError('orderDirection')
                                    }
                                }}
                                options={EXPERIMENTS_WIDGET_ORDER_DIRECTION_OPTIONS}
                            />
                        </LemonField.Pure>
                    </div>
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
