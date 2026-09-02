import { useActions, useValues } from 'kea'

import { LemonLabel, LemonModal, LemonSelect, LemonTag } from '@posthog/lemon-ui'
import { LemonButton, LemonColorPicker, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { BreakdownTag } from 'scenes/insights/filters/BreakdownFilter/BreakdownTag'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { dataColorThemesLogic } from 'scenes/settings/environment/dataColorThemesLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { DashboardMode } from '~/types'

import {
    BreakdownColorConfig,
    BreakdownValueAndType,
    COHORT_BREAKDOWN_PROPERTY_KEY,
    denormalizeBreakdownValue,
    findBreakdownColorConfig,
    parseBreakdownPropertyKey,
} from './dashboardBreakdownColors'
import { dashboardInsightColorsModalLogic } from './dashboardInsightColorsModalLogic'
import { dashboardLogic } from './dashboardLogic'

type BreakdownColorRow = BreakdownColorConfig & { pinnedConfig?: BreakdownColorConfig }

function BreakdownPropertyGroupTitle({ breakdownProperty }: { breakdownProperty?: string }): JSX.Element {
    if (breakdownProperty == null) {
        // The property-less group holds entries that apply under every property, like the funnel baseline.
        return <LemonTag type="muted">All properties</LemonTag>
    }
    if (breakdownProperty === COHORT_BREAKDOWN_PROPERTY_KEY) {
        return <LemonTag type="muted">Cohorts</LemonTag>
    }
    return (
        <div className="flex flex-wrap items-center gap-1">
            {parseBreakdownPropertyKey(breakdownProperty).map((part, index) => (
                <BreakdownTag key={index} breakdown={part.property} breakdownType={part.type} size="small" />
            ))}
        </div>
    )
}

export function DashboardInsightColorsModal(): JSX.Element {
    const { isOpen, insightTilesLoading, breakdownValueGroups } = useValues(dashboardInsightColorsModalLogic)
    const { hideInsightColorsModal, cancelColorChanges } = useActions(dashboardInsightColorsModalLogic)

    const { themes: _themes, themesLoading } = useValues(dataColorThemesLogic)

    const {
        effectiveBreakdownColors,
        dataColorThemeId,
        dashboardMode,
        dashboardLoading,
        canEditDashboard,
        hasUnsavedColorChanges,
    } = useValues(dashboardLogic)
    const { setBreakdownColorConfig, setDataColorThemeId, setDashboardMode } = useActions(dashboardLogic)

    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { allCohorts } = useValues(cohortsModel)

    const themes = _themes || []

    const ensureEditMode = (): void => {
        if (dashboardMode !== DashboardMode.Edit) {
            setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardInsightColorsModal)
        }
    }

    const toRow = (breakdownValue: BreakdownValueAndType): BreakdownColorRow => {
        const config = findBreakdownColorConfig(
            effectiveBreakdownColors,
            breakdownValue.breakdownValue,
            breakdownValue.breakdownType,
            breakdownValue.breakdownProperty
        )
        return {
            ...breakdownValue,
            colorToken: config?.colorToken || null,
            source: config?.source,
            pinnedConfig: config,
        }
    }

    const columns: LemonTableColumns<BreakdownColorRow> = [
        {
            title: 'Breakdown',
            key: 'breakdown_value',
            render: (_, { breakdownValue, breakdownType }) => {
                const breakdownFilter: BreakdownFilter = { breakdown_type: breakdownType }
                const breakdownLabel = formatBreakdownLabel(
                    denormalizeBreakdownValue(breakdownValue),
                    breakdownFilter,
                    allCohorts?.results,
                    formatPropertyValueForDisplay
                )
                const formattedLabel = stringWithWBR(breakdownLabel, 20)

                return <span>{formattedLabel}</span>
            },
        },
        {
            title: 'Color',
            key: 'color',
            render: (_, { colorToken, source, pinnedConfig, ...config }) => {
                return (
                    <div className="flex items-center gap-2">
                        <LemonColorPicker
                            selectedColorToken={colorToken}
                            onSelectColorToken={(colorToken) => {
                                ensureEditMode()
                                setBreakdownColorConfig({
                                    ...config,
                                    colorToken,
                                    source: 'manual',
                                })
                            }}
                            customButton={
                                colorToken === null ? (
                                    <LemonButton type="tertiary">Customize color</LemonButton>
                                ) : undefined
                            }
                            themeId={dataColorThemeId}
                        />
                        {source === 'auto' ? (
                            <LemonTag type="muted">Auto</LemonTag>
                        ) : colorToken !== null ? (
                            <LemonButton
                                size="small"
                                type="tertiary"
                                tooltip="Reset to automatic color"
                                onClick={() => {
                                    ensureEditMode()
                                    // Clearing must target the entry that provides the pin: a
                                    // property-less legacy pin cleared from a scoped row would
                                    // otherwise survive and keep coloring other properties.
                                    setBreakdownColorConfig({
                                        ...(pinnedConfig ?? config),
                                        colorToken: null,
                                        source: 'manual',
                                    })
                                }}
                            >
                                Reset
                            </LemonButton>
                        ) : null}
                    </div>
                )
            },
        },
    ]

    return (
        <LemonModal
            title="Customize breakdown colors"
            isOpen={isOpen}
            onClose={hideInsightColorsModal}
            maxWidth="42rem"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        data-attr="dashboard-colors-cancel"
                        onClick={cancelColorChanges}
                        tooltip="Revert the changes made in this dialog"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="dashboard-colors-save"
                        onClick={() => {
                            hideInsightColorsModal()
                            setDashboardMode(null, DashboardEventSource.DashboardInsightColorsModal)
                        }}
                        disabledReason={
                            dashboardLoading
                                ? 'Wait for dashboard to finish loading'
                                : !canEditDashboard
                                  ? 'Not privileged to edit this dashboard'
                                  : !hasUnsavedColorChanges
                                    ? 'No color changes to save'
                                    : undefined
                        }
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <LemonLabel info="Select a color theme for all insights on this dashboard. If a theme is selected, it will be applied to all series and breakdowns.">
                Color theme
            </LemonLabel>
            <LemonSelect
                className="mt-2"
                value={dataColorThemeId || null}
                placeholder="Defined by insight"
                onChange={(id) => {
                    ensureEditMode()
                    setDataColorThemeId(id)
                }}
                loading={themesLoading}
                options={themes.map((theme) => ({ value: theme.id, label: theme.name }))}
            />

            <LemonLabel
                className="mt-4 mb-2"
                info={
                    <>
                        <p className="mb-1">
                            Colors are grouped by breakdown property, so each property picks its colors on its own.
                        </p>
                        <ul className="list-disc pl-4 space-y-1">
                            <li>
                                A value shown on two or more insights gets one color across the dashboard, and keeps it
                                under every property it appears in, as far as the palette allows.
                            </li>
                            <li>Values on a single insight keep their own colors.</li>
                            <li>Pick a color to pin a value to it.</li>
                        </ul>
                    </>
                }
            >
                Breakdown colors
            </LemonLabel>
            {breakdownValueGroups.length === 0 ? (
                <LemonTable columns={columns} dataSource={[]} loading={insightTilesLoading || undefined} />
            ) : (
                breakdownValueGroups.map((group) => (
                    <div key={group.breakdownProperty ?? ''} className="mb-4">
                        <LemonLabel className="mb-1">
                            <BreakdownPropertyGroupTitle breakdownProperty={group.breakdownProperty} />
                        </LemonLabel>
                        <LemonTable columns={columns} dataSource={group.values.map(toRow)} showHeader={false} />
                    </div>
                ))
            )}
            {insightTilesLoading ? (
                <p className="text-muted-alt mt-2">Tiles are still loading. More breakdown values may appear.</p>
            ) : null}
        </LemonModal>
    )
}
