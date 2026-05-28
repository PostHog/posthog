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
import { teamLogic } from 'scenes/teamLogic'

import { exceptionIngestionLogic } from 'products/error_tracking/frontend/components/SetupPrompt/exceptionIngestionLogic'

import { resolveWidgetFilterTestAccounts } from '../../widget_types/configSchemas'
import { WIDGET_DATE_RANGE_SELECT_OPTIONS } from '../../widget_types/widgetDateRangeOptions'
import {
    validateErrorTrackingWidgetConfigInput,
    type ErrorTrackingWidgetFieldErrors,
} from './errorTrackingWidgetConfigValidation'
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
    canConfigureErrorTrackingWidgetIssues,
    ERROR_TRACKING_WIDGET_ORDER_BY_OPTIONS,
} from './utils'

export function EditErrorTrackingWidgetModal({
    isOpen,
    onClose,
    config,
    onSave,
    name = '',
    defaultTitle = 'Untitled',
    description = '',
    onSaveMetadata,
}: DashboardWidgetEditModalProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { filterTestAccountsDefault } = useValues(filterTestAccountsDefaultsLogic)
    const { hasSentExceptionEvent, hasSentExceptionEventLoading } = useValues(exceptionIngestionLogic)
    const showIssueSettings =
        canConfigureErrorTrackingWidgetIssues(currentTeam, hasSentExceptionEvent) &&
        !hasSentExceptionEventLoading &&
        !!currentTeam
    const initialDateRange = (config.dateRange as { date_from?: string } | undefined)?.date_from ?? '-7d'
    const [limit, setLimit] = useState<number>((config.limit as number) ?? 10)
    const [orderBy, setOrderBy] = useState<string>((config.orderBy as string) ?? 'occurrences')
    const [dateFrom, setDateFrom] = useState<string>(initialDateRange)
    const [tileName, setTileName] = useState<string>(name)
    const [tileDescription, setTileDescription] = useState<string>(description)
    const [filterTestAccounts, setFilterTestAccounts] = useState<boolean>(
        resolveWidgetFilterTestAccounts(config.filterTestAccounts as boolean | undefined, filterTestAccountsDefault)
    )
    const [fieldErrors, setFieldErrors] = useState<ErrorTrackingWidgetFieldErrors>({})
    const [saving, setSaving] = useState(false)

    useEffect(() => {
        if (isOpen) {
            setFieldErrors({})
            setTileName(name)
            setTileDescription(description)
            setFilterTestAccounts(
                resolveWidgetFilterTestAccounts(
                    config.filterTestAccounts as boolean | undefined,
                    filterTestAccountsDefault
                )
            )
        }
    }, [isOpen, name, description, config.filterTestAccounts, filterTestAccountsDefault])

    const validation = useMemo(
        () =>
            validateErrorTrackingWidgetConfigInput({
                limit,
                orderBy,
                dateFrom,
                filterTestAccounts,
                baseConfig: config,
            }),
        [limit, orderBy, dateFrom, filterTestAccounts, config]
    )

    const activeFieldErrors = useMemo((): ErrorTrackingWidgetFieldErrors => {
        if (!validation.success) {
            return { ...validation.fieldErrors, ...fieldErrors }
        }
        return fieldErrors
    }, [validation, fieldErrors])

    const clearFieldError = (field: keyof ErrorTrackingWidgetFieldErrors): void => {
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
        const result = validateErrorTrackingWidgetConfigInput({
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

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Widget settings"
            description={
                showIssueSettings
                    ? 'Configure tile details and which error tracking issues appear on this dashboard.'
                    : 'Configure tile details for this dashboard widget.'
            }
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
                            saving
                                ? 'Saving…'
                                : !validation.success
                                  ? 'Fix validation errors to save'
                                  : undefined
                        }
                        onClick={() => void handleSave()}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <WidgetSettingsModalSections>
                {onSaveMetadata && (
                    <WidgetSettingsModalSection title="Tile details">
                        <LemonField.Pure
                            className={WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS}
                            label="Title"
                            help="Shown on the tile. Leave empty to use the default title."
                        >
                            <LemonInput
                                value={tileName}
                                onChange={setTileName}
                                placeholder={defaultTitle}
                                maxLength={400}
                                disabled={saving}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure
                            className={WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS}
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
                    </WidgetSettingsModalSection>
                )}
                {showIssueSettings && (
                    <>
                        {onSaveMetadata && <WidgetSettingsModalDivider />}
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
                        <WidgetSettingsModalSection
                            title={DASHBOARD_WIDGET_CATALOG.error_tracking_list.groupLabel}
                        >
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
                                className={WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS}
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
                        </WidgetSettingsModalSection>
                    </>
                )}
            </WidgetSettingsModalSections>
        </LemonModal>
    )
}
