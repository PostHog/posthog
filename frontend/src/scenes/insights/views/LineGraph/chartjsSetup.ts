import { Chart, registerables, Tooltip } from 'chart.js'
import CrosshairPlugin from 'chartjs-plugin-crosshair'

if (registerables) {
    // required for storybook to work, not found in esbuild
    Chart.register(...registerables)
}
Chart.register(CrosshairPlugin)
Chart.defaults.animation['duration'] = 0

// Create positioner to put tooltip at cursor position
Tooltip.positioners.cursor = function (_, coordinates) {
    return coordinates
}
