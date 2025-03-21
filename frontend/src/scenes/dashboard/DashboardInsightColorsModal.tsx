import { LemonModal } from '@posthog/lemon-ui'
import { LemonColorPicker, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
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

    const columns: LemonTableColumns<string> = [
        {
            title: 'Color',
            key: 'color',
            render: (_, breakdownValue) => {
                return (
                    <LemonColorPicker
                        selectedColorToken={temporaryBreakdownColors[breakdownValue] || null}
                        onSelectColorToken={(colorToken) => {
                            if (dashboardMode !== DashboardMode.Edit) {
                                setDashboardMode(DashboardMode.Edit, null)
                            }

                            setBreakdownColor(breakdownValue, colorToken)
                        }}
                    />
                )
            },
        },
        {
            title: 'Breakdown',
            key: 'breakdown_value',
            // width: 0,
            render: (_, breakdownValue) => {
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
    ]

    return (
        <LemonModal title="Customize Colors" isOpen={isOpen} onClose={hideInsightColorsModal}>
            {insightTilesLoading ? (
                <div className="flex flex-col items-center">
                    {/* Slightly offset to the left for visual balance. */}
                    <Animation type={AnimationType.SportsHog} size="large" className="-ml-4" />
                    <p className="text-primary">Waiting for dashboard tiles to load and refresh…</p>
                </div>
            ) : (
                <>
                    <LemonTable columns={columns} dataSource={breakdownValues} loading={insightTilesLoading} />
                </>
            )}
        </LemonModal>
    )
}
