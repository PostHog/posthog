import { useActions, useValues } from 'kea'

import { LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { LemonButton, LemonColorPicker, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { AnimationType } from 'lib/animations/animations'
import { DataColorToken } from 'lib/colors'
import { Animation } from 'lib/components/Animation/Animation'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { dataColorThemesLogic } from 'scenes/settings/environment/dataColorThemesLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { DashboardMode } from '~/types'

import { dashboardInsightColorsModalLogic } from './dashboardInsightColorsModalLogic'
import { dashboardLogic } from './dashboardLogic'

export type BreakdownColorConfig = {
    colorToken: DataColorToken | null
    breakdownValue: string
    breakdownType: BreakdownFilter['breakdown_type']
}

export function DashboardInsightColorsModal(): JSX.Element {
    const { isOpen, insightTilesLoading, breakdownValues } = useValues(dashboardInsightColorsModalLogic)
    const { hideInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)

    const { themes: _themes, themesLoading } = useValues(dataColorThemesLogic)

    const {
        temporaryBreakdownColors: dashboardBreakdownColors,
        dataColorThemeId,
        dashboardMode,
    } = useValues(dashboardLogic)
    const { setBreakdownColorConfig, setDataColorThemeId, setDashboardMode } = useActions(dashboardLogic)

    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { allCohorts } = useValues(cohortsModel)

    const themes = _themes || []

    const columns: LemonTableColumns<BreakdownColorConfig> = [
        {
            title: 'Breakdown',
            key: 'breakdown_value',
            render: (_, { breakdownValue, ...config }) => {
                const breakdownFilter: BreakdownFilter = { breakdown_type: config.breakdownType }
                const breakdownLabel = formatBreakdownLabel(
                    breakdownValue,
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
            width: 400,
            render: (_, { colorToken, ...config }) => {
                return (
                    <LemonColorPicker
                        selectedColorToken={colorToken}
                        onSelectColorToken={(colorToken) => {
                            if (dashboardMode !== DashboardMode.Edit) {
                                setDashboardMode(DashboardMode.Edit, null)
                            }

                            setBreakdownColorConfig({
                                ...config,
                                colorToken,
                            })
                        }}
                        customButton={
                            colorToken === null ? <LemonButton type="tertiary">Customize color</LemonButton> : undefined
                        }
                        themeId={dataColorThemeId}
                    />
                )
            },
        },
    ]

    return (
        <LemonModal title="Customize Breakdown Colors" isOpen={isOpen} onClose={hideInsightColorsModal}>
            <LemonLabel info="Select a color theme for all insights on this dashboard. If a theme is selected, it will be applied to all series and breakdowns.">
                Color theme
            </LemonLabel>
            <LemonSelect
                className="mt-2"
                value={dataColorThemeId || null}
                placeholder="Defined by insight"
                onChange={(id) => {
                    if (dashboardMode !== DashboardMode.Edit) {
                        setDashboardMode(DashboardMode.Edit, null)
                    }

                    setDataColorThemeId(id)
                }}
                loading={themesLoading}
                options={themes.map((theme) => ({ value: theme.id, label: theme.name }))}
            />

            <LemonLabel className="mt-4">Breakdown colors</LemonLabel>
            <p className="text-muted-alt mb-4">
                Assign custom colors to breakdown values that will be used consistently across all insights on this
                dashboard. <i>Note: This feature currently only works for trend and step-based funnel insights.</i>
            </p>
            {insightTilesLoading ? (
                <div className="flex flex-col items-center">
                    {/* Slightly offset to the left for visual balance. */}
                    <Animation type={AnimationType.SportsHog} size="large" className="-ml-4" />
                    <p className="text-primary">Waiting for dashboard tiles to load and refresh…</p>
                </div>
            ) : (
                <>
                    <LemonTable
                        columns={columns}
                        dataSource={breakdownValues.map((breakdownValue) => ({
                            ...breakdownValue,
                            colorToken:
                                dashboardBreakdownColors.find(
                                    (c) =>
                                        c.breakdownValue === breakdownValue.breakdownValue &&
                                        c.breakdownType === breakdownValue.breakdownType
                                )?.colorToken || null,
                        }))}
                        loading={insightTilesLoading || undefined}
                    />
                </>
            )}
        </LemonModal>
    )
}
