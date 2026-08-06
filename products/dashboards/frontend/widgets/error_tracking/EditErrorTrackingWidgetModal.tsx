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
import { editErrorTrackingWidgetModalLogic } from './editErrorTrackingWidgetModalLogic'
import { ERROR_TRACKING_WIDGET_ORDER_BY_OPTIONS } from './utils'

function EditErrorTrackingWidgetModalContents(): JSX.Element {
    const {
        showIssueSettings,
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
    } = useValues(editErrorTrackingWidgetModalLogic)
    const {
        setLimit,
        setOrderBy,
        setOrderDirection,
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
                        <section className="flex flex-col gap-3">
                            <h5 className="text-sm font-semibold m-0">
                                {getDashboardWidgetGroupLabel('error_tracking')}
                            </h5>
                            <div className="flex flex-col gap-4">
                                <EditWidgetModalFiltersSubsection
                                    title="Issue filters"
                                    filterTestAccounts={filterTestAccounts}
                                    saving={saving}
                                    setFilterTestAccounts={setFilterTestAccounts}
                                >
                                    <p className="text-sm text-muted m-0 sm:col-span-2">
                                        Date range, status, and assignee are on the tile filter bar (collapsible on the
                                        tile). Use this modal for test-account filtering, list size, and sort.
                                    </p>
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
                                </div>
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
