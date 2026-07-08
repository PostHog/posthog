import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import { EditWidgetModalTileDetailsSection } from '../EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from '../registry'
import { editLogsWidgetModalLogic } from './editLogsWidgetModalLogic'
import type { LogsTimezone } from './logsWidgetConfigValidation'

const TIMEZONE_OPTIONS: { value: LogsTimezone; label: string }[] = [
    { value: 'UTC', label: 'UTC' },
    { value: 'local', label: 'Local time' },
]

function EditLogsWidgetModalContents(): JSX.Element {
    const {
        limit,
        wrapLines,
        timezone,
        dateFrom,
        tileName,
        tileDescription,
        activeFieldErrors,
        saving,
        saveDisabledReason,
        onClose,
        defaultTitle,
    } = useValues(editLogsWidgetModalLogic)
    const {
        setLimit,
        setWrapLines,
        setTimezone,
        setDateFrom,
        setTileName,
        setTileDescription,
        clearFieldError,
        submit,
    } = useActions(editLogsWidgetModalLogic)

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Widget settings"
            description="Configure tile details and which logs appear on this dashboard."
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
                    <h5 className="text-sm font-semibold m-0">{getDashboardWidgetGroupLabel('logs')}</h5>
                    <p className="text-sm text-muted m-0">
                        Severity, service, and sort filters live on the tile filter bar. Use this modal for the date
                        range and how many log lines to show.
                    </p>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <LemonField.Pure label="Date range">
                            <LemonSelect
                                value={dateFrom as WidgetDateFromValue}
                                disabled={saving}
                                options={WIDGET_DATE_RANGE_SELECT_OPTIONS}
                                onChange={(value) => {
                                    if (value) {
                                        setDateFrom(value)
                                    }
                                }}
                                fullWidth
                            />
                        </LemonField.Pure>
                        <LemonField.Pure
                            label="Number of log lines"
                            help="Show up to 100 log lines on the tile."
                            error={activeFieldErrors.limit}
                        >
                            <LemonInput
                                type="number"
                                min={1}
                                max={100}
                                fullWidth
                                value={limit}
                                onChange={(value) => {
                                    setLimit(Number(value))
                                    clearFieldError('limit')
                                }}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Timestamps" help="Display log times in UTC or your local timezone.">
                            <LemonSelect
                                value={timezone}
                                disabled={saving}
                                options={TIMEZONE_OPTIONS}
                                onChange={(value) => {
                                    if (value) {
                                        setTimezone(value)
                                    }
                                }}
                                fullWidth
                            />
                        </LemonField.Pure>
                    </div>
                    <LemonSwitch
                        checked={wrapLines}
                        onChange={setWrapLines}
                        disabled={saving}
                        label="Wrap long log lines"
                        bordered
                    />
                </section>
            </div>
        </LemonModal>
    )
}

export function EditLogsWidgetModal({
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
            logic={editLogsWidgetModalLogic}
            props={{ onClose, config, onSave, name, defaultTitle, description }}
        >
            <EditLogsWidgetModalContents />
        </BindLogic>
    )
}
