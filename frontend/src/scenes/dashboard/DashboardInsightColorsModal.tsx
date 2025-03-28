import { LemonModal } from '@posthog/lemon-ui'
import { LemonButton, LemonColorPicker, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { DataColorToken } from 'lib/colors'
import { Animation } from 'lib/components/Animation/Animation'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { formatBreakdownLabel } from 'scenes/insights/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { DashboardMode } from '~/types'

import { dashboardInsightColorsModalLogic } from './dashboardInsightColorsModalLogic'
import { dashboardLogic } from './dashboardLogic'

export function DashboardInsightColorsModal(): JSX.Element {
    const { isOpen, insightTilesLoading, breakdownValues } = useValues(dashboardInsightColorsModalLogic)
    const { hideInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)

    const { temporaryBreakdownColors, dashboardMode } = useValues(dashboardLogic)
    const { setBreakdownColor, setDashboardMode } = useActions(dashboardLogic)

    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { cohorts } = useValues(cohortsModel)

    const columns: LemonTableColumns<{ breakdownValue: string; colorToken: DataColorToken | null }> = [
        {
            title: 'Breakdown',
            key: 'breakdown_value',
            render: (_, { breakdownValue }) => {
                // TODO: support for cohorts and nested breakdowns
                const breakdownFilter = {}
                const breakdownLabel = formatBreakdownLabel(
                    breakdownValue,
                    breakdownFilter,
                    cohorts?.results,
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
            render: (_, { breakdownValue, colorToken }) => {
                return (
                    <LemonColorPicker
                        selectedColorToken={colorToken}
                        onSelectColorToken={(colorToken) => {
                            if (dashboardMode !== DashboardMode.Edit) {
                                setDashboardMode(DashboardMode.Edit, null)
                            }

                            setBreakdownColor(breakdownValue, colorToken)
                        }}
                        customButton={
                            colorToken === null ? <LemonButton type="tertiary">Customize color</LemonButton> : undefined
                        }
                    />
                )
            },
        },
    ]

    return (
        <LemonModal title="Customize Breakdown Colors" isOpen={isOpen} onClose={hideInsightColorsModal}>
            <p className="text-muted-alt mb-4">
                Assign custom colors to breakdown values that will be used consistently across all insights on this
                dashboard. When you assign a color to a value, it will be used for that value in every insight where it
                appears.
            </p>
            <p className="text-muted-alt mb-4">
                <i>Note: This feature currently only works for trend and funnel insights.</i>
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
                            breakdownValue,
                            colorToken: temporaryBreakdownColors[breakdownValue] || null,
                        }))}
                        loading={insightTilesLoading || undefined}
                    />
                </>
            )}
        </LemonModal>
    )
}
