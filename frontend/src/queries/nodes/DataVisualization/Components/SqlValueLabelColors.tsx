import posthog from 'posthog-js'

import { LemonColorPicker, LemonLabel } from '@posthog/lemon-ui'

import { getSeriesColorPalette } from 'lib/colors'

import { ChartSettings } from '~/queries/schema/schema-general'

export function SqlValueLabelColors({
    chartSettings,
    updateChartSettings,
}: {
    chartSettings: ChartSettings
    updateChartSettings: (settings: ChartSettings) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {(
                [
                    ['valueLabelColor', 'Value text color'],
                    ['valueLabelBackgroundColor', 'Value background color'],
                ] as const
            ).map(([key, label]) =>
                key === 'valueLabelBackgroundColor' && chartSettings.valueLabelBackground === false ? null : (
                    <div key={key} className="flex items-center justify-between gap-2">
                        <LemonLabel>{label}</LemonLabel>
                        <LemonColorPicker
                            colors={getSeriesColorPalette()}
                            selectedColor={chartSettings[key] ?? null}
                            onSelectColor={(color) => {
                                updateChartSettings({ [key]: color })
                                posthog.capture('sql value label color updated', { setting: key, cleared: false })
                            }}
                            onClearColor={() => {
                                updateChartSettings({ [key]: undefined })
                                posthog.capture('sql value label color updated', { setting: key, cleared: true })
                            }}
                            showCustomColor
                            preventPopoverClose
                        />
                    </div>
                )
            )}
        </div>
    )
}
