import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { WIDGET_DATE_RANGE_SELECT_OPTIONS } from '../../widget_types/configSchemas'
import { EditWidgetModalFiltersSection } from '../EditWidgetModalFiltersSection'
import { EditWidgetModalTileDetailsSection } from '../EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from '../registry'
import { editErrorTrackingWidgetModalLogic } from './editErrorTrackingWidgetModalLogic'
import { ERROR_TRACKING_WIDGET_ORDER_BY_OPTIONS } from './utils'

function EditErrorTrackingWidgetModalContents(): JSX.Element {
    const {
        showIssueSettings,
        limit,
        orderBy,
        dateFrom,
        tileName,
        tileDescription,
        filterTestAccounts,
        activeFieldErrors,
        saving,
        saveDisabledReason,
        onClose,
        defaultTitle,
    } = useValues(editErrorTrackingWidgetModalLogic)
    const {
        setLimit,
        setOrderBy,
        setDateFrom,
        setTileName,
        setTileDescription,
        setFilterTestAccounts,
        clearFieldError,
        submit,
    } = useActions(editErrorTrackingWidgetModalLogic)

    const showTileDetails = true

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Widget settings"
            description={
                showIssueSettings
                    ? 'Configure tile details and which error tracking issues appear on this dashboard.'
                    : 'Configure tile details for this dashboard widget.'
            }
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
                {showIssueSettings ? (
                    <>
                        {showTileDetails ? <LemonDivider className="my-0" /> : null}
                        <EditWidgetModalFiltersSection
                            filterTestAccounts={filterTestAccounts}
                            saving={saving}
                            setFilterTestAccounts={setFilterTestAccounts}
                        />
                        <LemonDivider className="my-0" />
                        <section className="flex flex-col gap-3">
                            <h5 className="text-sm font-semibold m-0">
                                {getDashboardWidgetGroupLabel('error_tracking')}
                            </h5>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <LemonField.Pure
                                    label="Date range"
                                    help="Only include issues seen in this period."
                                    error={activeFieldErrors.dateFrom}
                                >
                                    <LemonSelect
                                        fullWidth
                                        value={dateFrom}
                                        onChange={(value) => {
                                            setDateFrom(value)
                                            clearFieldError('dateFrom')
                                        }}
                                        options={WIDGET_DATE_RANGE_SELECT_OPTIONS}
                                    />
                                </LemonField.Pure>
                                <LemonField.Pure
                                    label="Number of issues"
                                    help="Show up to 25 issues on the tile."
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
                                <LemonField.Pure
                                    className="sm:col-span-2"
                                    label="Sort by"
                                    help="Order issues by this metric within the date range."
                                    error={activeFieldErrors.orderBy}
                                >
                                    <LemonSelect
                                        fullWidth
                                        value={orderBy}
                                        onChange={(value) => {
                                            setOrderBy(value)
                                            clearFieldError('orderBy')
                                        }}
                                        options={[...ERROR_TRACKING_WIDGET_ORDER_BY_OPTIONS]}
                                    />
                                </LemonField.Pure>
                            </div>
                        </section>
                    </>
                ) : null}
            </div>
        </LemonModal>
    )
}

export function EditErrorTrackingWidgetModal({
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
            logic={editErrorTrackingWidgetModalLogic}
            props={{ onClose, config, onSave, name, defaultTitle, description }}
        >
            <EditErrorTrackingWidgetModalContents />
        </BindLogic>
    )
}
