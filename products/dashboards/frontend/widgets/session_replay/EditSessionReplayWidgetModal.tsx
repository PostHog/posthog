import { BindLogic, useActions, useValues } from 'kea'

import { LemonTextArea } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { DASHBOARD_WIDGET_CATALOG } from '../../widget_types/catalog'
import { WIDGET_DATE_RANGE_SELECT_OPTIONS } from '../../widget_types/configSchemas'
import type { DashboardWidgetEditModalProps } from '../registry'
import {
    editSessionReplayWidgetModalLogic,
    type EditSessionReplayWidgetModalLogicProps,
} from './editSessionReplayWidgetModalLogic'
import { SESSION_REPLAY_WIDGET_ORDER_BY_OPTIONS } from './utils'

const widgetSettingsFieldFullWidthClass = 'sm:col-span-2'

function EditSessionReplayWidgetModalForm(props: EditSessionReplayWidgetModalLogicProps): JSX.Element {
    const {
        limit,
        orderBy,
        dateFrom,
        tileName,
        tileDescription,
        filterTestAccounts,
        activeFieldErrors,
        saving,
        saveDisabledReason,
    } = useValues(editSessionReplayWidgetModalLogic)
    const {
        setLimit,
        setOrderBy,
        setDateFrom,
        setTileName,
        setTileDescription,
        setFilterTestAccounts,
        clearFieldError,
        submit,
    } = useActions(editSessionReplayWidgetModalLogic)

    const catalogEntry = DASHBOARD_WIDGET_CATALOG.session_replay_list

    return (
        <LemonModal
            isOpen
            onClose={props.onClose}
            title="Widget settings"
            description="Configure tile details and which session recordings appear on this dashboard."
            width={680}
            footer={
                <>
                    <div className="flex-1" />
                    <LemonButton type="secondary" onClick={props.onClose} disabled={saving}>
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
                {props.onSaveMetadata && (
                    <section className="flex flex-col gap-3">
                        <h5 className="text-sm font-semibold m-0">Tile details</h5>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <LemonField.Pure
                                className={widgetSettingsFieldFullWidthClass}
                                label="Title"
                                help="Shown on the tile. Leave empty to use the default title."
                            >
                                <LemonInput
                                    value={tileName}
                                    onChange={setTileName}
                                    placeholder={props.defaultTitle ?? 'Untitled'}
                                    maxLength={400}
                                    disabled={saving}
                                />
                            </LemonField.Pure>
                            <LemonField.Pure
                                className={widgetSettingsFieldFullWidthClass}
                                label="Description"
                                help="Shown under the tile title. Supports markdown. Leave empty to hide."
                            >
                                <LemonTextArea
                                    value={tileDescription}
                                    onChange={setTileDescription}
                                    placeholder="Enter description (optional)"
                                    minRows={2}
                                    disabled={saving}
                                />
                            </LemonField.Pure>
                        </div>
                    </section>
                )}
                <>
                    {props.onSaveMetadata && <LemonDivider className="my-0" />}
                    <section className="flex flex-col gap-3">
                        <h5 className="text-sm font-semibold m-0">Filters</h5>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <div className={widgetSettingsFieldFullWidthClass}>
                                <TestAccountFilter
                                    size="small"
                                    filters={{ filter_test_accounts: filterTestAccounts }}
                                    onChange={({ filter_test_accounts }) =>
                                        setFilterTestAccounts(filter_test_accounts ?? false)
                                    }
                                    disabledReason={saving ? 'Saving…' : undefined}
                                />
                            </div>
                        </div>
                    </section>
                    <LemonDivider className="my-0" />
                    <section className="flex flex-col gap-3">
                        <h5 className="text-sm font-semibold m-0">{catalogEntry.groupLabel}</h5>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <LemonField.Pure
                                label="Date range"
                                help="Only include recordings started in this period."
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
                            <LemonField.Pure
                                className={widgetSettingsFieldFullWidthClass}
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
                    </section>
                </>
            </div>
        </LemonModal>
    )
}

export function EditSessionReplayWidgetModal({
    isOpen,
    ...formProps
}: DashboardWidgetEditModalProps): JSX.Element | null {
    if (!isOpen) {
        return null
    }

    return (
        <BindLogic logic={editSessionReplayWidgetModalLogic} props={formProps}>
            <EditSessionReplayWidgetModalForm {...formProps} />
        </BindLogic>
    )
}
