import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { WIDGET_LIST_ORDER_DIRECTION_OPTIONS } from '../constants'
import { EditWidgetModalFiltersSubsection } from '../EditWidgetModalFiltersSection'
import { EditWidgetModalTileDetailsSection } from '../EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from '../registry'
import { editSessionReplayWidgetModalLogic } from './editSessionReplayWidgetModalLogic'

export const SESSION_REPLAY_WIDGET_ORDER_BY_OPTIONS = [
    { value: 'start_time', label: 'Start time' },
    { value: 'activity_score', label: 'Activity score' },
    { value: 'recording_duration', label: 'Duration' },
    { value: 'click_count', label: 'Clicks' },
    { value: 'console_error_count', label: 'Console errors' },
] as const

function EditSessionReplayWidgetModalContents(): JSX.Element {
    const {
        limit,
        orderBy,
        orderDirection,
        tileName,
        tileDescription,
        filterTestAccounts,
        activeFieldErrors,
        saving,
        saveDisabledReason,
        onClose,
        defaultTitle,
    } = useValues(editSessionReplayWidgetModalLogic)
    const {
        setLimit,
        setOrderBy,
        setOrderDirection,
        setTileName,
        setTileDescription,
        setFilterTestAccounts,
        clearFieldError,
        submit,
    } = useActions(editSessionReplayWidgetModalLogic)

    const showTileDetails = true

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Widget settings"
            description="Configure tile details and which session recordings appear on this dashboard."
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
                {showTileDetails ? (
                    <EditWidgetModalTileDetailsSection
                        tileName={tileName}
                        tileDescription={tileDescription}
                        defaultTitle={defaultTitle}
                        saving={saving}
                        setTileName={setTileName}
                        setTileDescription={setTileDescription}
                    />
                ) : null}
                {showTileDetails ? <LemonDivider className="my-0" /> : null}
                <section className="flex flex-col gap-3">
                    <h5 className="text-sm font-semibold m-0">{getDashboardWidgetGroupLabel('session_replay')}</h5>
                    <div className="flex flex-col gap-4">
                        <EditWidgetModalFiltersSubsection
                            title="Recording filters"
                            filterTestAccounts={filterTestAccounts}
                            saving={saving}
                            setFilterTestAccounts={setFilterTestAccounts}
                        >
                            <p className="text-sm text-muted m-0 sm:col-span-2">
                                Date range, property filters, and saved filters are on the tile filter bar (collapsible
                                on the tile). Use this modal for test-account filtering, list size, and sort.
                            </p>
                            <LemonField.Pure
                                label="Number of recordings"
                                help="Show up to 25 recordings on the tile."
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
                        </EditWidgetModalFiltersSubsection>
                        <div className="flex flex-col gap-3">
                            <h6 className="text-xs font-semibold text-muted m-0">Sorting</h6>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <LemonField.Pure label="Sort direction" help="Ascending or descending sort.">
                                    <LemonSelect
                                        fullWidth
                                        value={orderDirection}
                                        onChange={(value) => setOrderDirection(value)}
                                        options={[...WIDGET_LIST_ORDER_DIRECTION_OPTIONS]}
                                    />
                                </LemonField.Pure>
                                <LemonField.Pure
                                    label="Sort by"
                                    help="Order recordings by this metric within the date range."
                                    error={activeFieldErrors.orderBy}
                                >
                                    <LemonSelect
                                        fullWidth
                                        value={orderBy}
                                        onChange={(value) => {
                                            setOrderBy(value)
                                            clearFieldError('orderBy')
                                        }}
                                        options={[...SESSION_REPLAY_WIDGET_ORDER_BY_OPTIONS]}
                                    />
                                </LemonField.Pure>
                            </div>
                        </div>
                    </div>
                </section>
            </div>
        </LemonModal>
    )
}

export function EditSessionReplayWidgetModal({
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
            logic={editSessionReplayWidgetModalLogic}
            props={{ onClose, config, onSave, name, defaultTitle, description }}
        >
            <EditSessionReplayWidgetModalContents />
        </BindLogic>
    )
}
