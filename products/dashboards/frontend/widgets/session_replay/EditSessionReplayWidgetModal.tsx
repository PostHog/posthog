import { useEffect, useMemo, useState } from 'react'
import { useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from '@posthog/lemon-ui'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { resolveWidgetFilterTestAccounts } from '../../widget_types/configSchemas'
import { WIDGET_DATE_RANGE_SELECT_OPTIONS } from '../../widget_types/widgetDateRangeOptions'
import { isWidgetConfigValidationError } from '../../widget_types/widgetConfigValidation'
import { DASHBOARD_WIDGET_CATALOG } from '../../widget_types/catalog'
import { DASHBOARD_WIDGET_MODAL_WIDTH } from '../constants'
import type { DashboardWidgetEditModalProps } from '../registry'
import {
    WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS,
    WidgetSettingsModalDivider,
    WidgetSettingsModalSection,
    WidgetSettingsModalSections,
} from '../WidgetSettingsModalSections'
import {
    validateSessionReplayWidgetConfigInput,
    type SessionReplayWidgetFieldErrors,
} from './sessionReplayWidgetConfigValidation'
import { SESSION_REPLAY_WIDGET_ORDER_BY_OPTIONS } from './utils'

export function EditSessionReplayWidgetModal({
    isOpen,
    onClose,
    config,
    onSave,
    name = '',
    defaultTitle = 'Untitled',
    description = '',
    onSaveMetadata,
}: DashboardWidgetEditModalProps): JSX.Element {
    const { filterTestAccountsDefault } = useValues(filterTestAccountsDefaultsLogic)
    const initialDateRange = (config.dateRange as { date_from?: string } | undefined)?.date_from ?? '-7d'
    const [limit, setLimit] = useState<number>((config.limit as number) ?? 10)
    const [orderBy, setOrderBy] = useState<string>((config.orderBy as string) ?? 'start_time')
    const [dateFrom, setDateFrom] = useState<string>(initialDateRange)
    const [tileName, setTileName] = useState<string>(name)
    const [tileDescription, setTileDescription] = useState<string>(description)
    const [filterTestAccounts, setFilterTestAccounts] = useState<boolean>(
        resolveWidgetFilterTestAccounts(config.filterTestAccounts as boolean | undefined, filterTestAccountsDefault)
    )
    const [fieldErrors, setFieldErrors] = useState<SessionReplayWidgetFieldErrors>({})
    const [saving, setSaving] = useState(false)

    useEffect(() => {
        if (isOpen) {
            setFieldErrors({})
            setTileName(name)
            setTileDescription(description)
            setLimit((config.limit as number) ?? 10)
            setOrderBy((config.orderBy as string) ?? 'start_time')
            setDateFrom((config.dateRange as { date_from?: string } | undefined)?.date_from ?? '-7d')
            setFilterTestAccounts(
                resolveWidgetFilterTestAccounts(
                    config.filterTestAccounts as boolean | undefined,
                    filterTestAccountsDefault
                )
            )
        }
    }, [isOpen, name, description, config, filterTestAccountsDefault])

    const validation = useMemo(
        () =>
            validateSessionReplayWidgetConfigInput({
                limit,
                orderBy,
                dateFrom,
                filterTestAccounts,
                baseConfig: config,
            }),
        [limit, orderBy, dateFrom, filterTestAccounts, config]
    )

    const activeFieldErrors = useMemo((): SessionReplayWidgetFieldErrors => {
        if (!validation.success) {
            return { ...validation.fieldErrors, ...fieldErrors }
        }
        return fieldErrors
    }, [validation, fieldErrors])

    const clearFieldError = (field: keyof SessionReplayWidgetFieldErrors): void => {
        setFieldErrors((current) => {
            if (!current[field]) {
                return current
            }
            const next = { ...current }
            delete next[field]
            return next
        })
    }

    const handleSave = async (): Promise<void> => {
        const result = validateSessionReplayWidgetConfigInput({
            limit,
            orderBy,
            dateFrom,
            filterTestAccounts,
            baseConfig: config,
        })

        if (!result.success) {
            setFieldErrors(result.fieldErrors)
            return
        }

        setSaving(true)
        try {
            const trimmedName = tileName.trim()
            const trimmedDescription = tileDescription.trim()
            const nameChanged = trimmedName !== name.trim()
            const descriptionChanged = trimmedDescription !== description.trim()

            await onSave(result.config)
            if (onSaveMetadata) {
                const metadata: { name?: string; description?: string } = {}
                if (nameChanged) {
                    metadata.name = trimmedName === defaultTitle.trim() ? '' : trimmedName
                }
                if (descriptionChanged) {
                    metadata.description = trimmedDescription
                }
                if (Object.keys(metadata).length > 0) {
                    await onSaveMetadata(metadata)
                }
            }
            setFieldErrors({})
            onClose()
        } catch (error) {
            if (isWidgetConfigValidationError(error)) {
                setFieldErrors(error.fieldErrors)
                return
            }
            throw error
        } finally {
            setSaving(false)
        }
    }

    const catalogEntry = DASHBOARD_WIDGET_CATALOG.session_replay_list

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Widget settings"
            description="Configure tile details and which session recordings appear on this dashboard."
            width={DASHBOARD_WIDGET_MODAL_WIDTH}
            footer={
                <>
                    <div className="flex-1" />
                    <LemonButton type="secondary" onClick={onClose} disabled={saving}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={saving}
                        disabledReason={
                            saving ? 'Saving…' : !validation.success ? 'Fix validation errors to save' : undefined
                        }
                        onClick={() => void handleSave()}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <WidgetSettingsModalSections>
                <WidgetSettingsModalSection title="Tile details">
                    <LemonField.Pure
                        className={WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS}
                        label="Name"
                    >
                        <LemonInput
                            value={tileName}
                            onChange={setTileName}
                            placeholder={defaultTitle}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        className={WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS}
                        label="Description"
                    >
                        <LemonTextArea
                            value={tileDescription}
                            onChange={setTileDescription}
                            placeholder={catalogEntry.description}
                        />
                    </LemonField.Pure>
                </WidgetSettingsModalSection>

                <WidgetSettingsModalDivider />

                <WidgetSettingsModalSection title="Filters">
                    <div className={WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS}>
                        <TestAccountFilter
                            size="small"
                            filters={{ filter_test_accounts: filterTestAccounts }}
                            onChange={({ filter_test_accounts }) =>
                                setFilterTestAccounts(filter_test_accounts ?? false)
                            }
                            disabledReason={saving ? 'Saving…' : undefined}
                        />
                    </div>
                </WidgetSettingsModalSection>

                <WidgetSettingsModalDivider />

                <WidgetSettingsModalSection title={catalogEntry.groupLabel}>
                    <LemonField.Pure label="Date range" error={activeFieldErrors.dateFrom}>
                        <LemonSelect
                            className={WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS}
                            value={dateFrom}
                            onChange={(value) => {
                                setDateFrom(value)
                                clearFieldError('dateFrom')
                            }}
                            options={WIDGET_DATE_RANGE_SELECT_OPTIONS}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Sort by" error={activeFieldErrors.orderBy}>
                        <LemonSelect
                            className={WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS}
                            value={orderBy}
                            onChange={(value) => {
                                setOrderBy(value)
                                clearFieldError('orderBy')
                            }}
                            options={[...SESSION_REPLAY_WIDGET_ORDER_BY_OPTIONS]}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Number of recordings" error={activeFieldErrors.limit}>
                        <LemonInput
                            className={WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS}
                            type="number"
                            min={1}
                            max={25}
                            value={limit}
                            onChange={(value) => {
                                setLimit(Number.isFinite(value) ? (value as number) : 10)
                                clearFieldError('limit')
                            }}
                        />
                    </LemonField.Pure>
                </WidgetSettingsModalSection>
            </WidgetSettingsModalSections>
        </LemonModal>
    )
}
