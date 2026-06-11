import { BindLogic, useActions, useValues } from 'kea'

import { MemberSelect } from 'lib/components/MemberSelect'
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
import type { ExperimentsListWidgetStatus } from './experimentsListWidgetConfigValidation'

export const EXPERIMENTS_WIDGET_STATUS_OPTIONS: { value: ExperimentsListWidgetStatus; label: string }[] = [
    { value: 'all', label: 'Any status' },
    { value: 'draft', label: 'Draft' },
    { value: 'running', label: 'Running' },
    { value: 'paused', label: 'Paused' },
    { value: 'stopped', label: 'Complete' },
]

function EditExperimentsListWidgetModalContents(): JSX.Element {
    const {
        limit,
        status,
        createdBy,
        tileName,
        tileDescription,
        activeFieldErrors,
        saving,
        saveDisabledReason,
        onClose,
        defaultTitle,
    } = useValues(editExperimentsListWidgetModalLogic)
    const { setLimit, setStatus, setCreatedBy, setTileName, setTileDescription, clearFieldError, submit } = useActions(
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
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <LemonField.Pure
                            label="Status"
                            help="Only show experiments with this status."
                            error={activeFieldErrors.status}
                        >
                            <LemonSelect
                                fullWidth
                                value={status}
                                onChange={(value) => {
                                    setStatus(value)
                                    clearFieldError('status')
                                }}
                                options={EXPERIMENTS_WIDGET_STATUS_OPTIONS}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure
                            label="Creator"
                            help="Only show experiments created by this person."
                            error={activeFieldErrors.createdBy}
                        >
                            <MemberSelect
                                type="secondary"
                                value={createdBy}
                                onChange={(user) => {
                                    setCreatedBy(user?.id ?? null)
                                    clearFieldError('createdBy')
                                }}
                            />
                        </LemonField.Pure>
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
                    </div>
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
