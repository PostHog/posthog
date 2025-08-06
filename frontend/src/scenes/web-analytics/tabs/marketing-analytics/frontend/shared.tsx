import { IconGraph, IconLineGraph } from '@posthog/icons'
import { LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { ChartDisplayType } from '~/types'

// Simple mapping for the display mode options and their icons
export const DISPLAY_MODE_OPTIONS: LemonSegmentedButtonOption<ChartDisplayType>[] = [
    { value: ChartDisplayType.ActionsLineGraph, icon: <IconLineGraph /> },
    { value: ChartDisplayType.ActionsAreaGraph, icon: <IconAreaChart /> },
    { value: ChartDisplayType.ActionsBar, icon: <IconGraph /> },
]
