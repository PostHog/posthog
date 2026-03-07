import { useMemo } from 'react'

import { buildBarConfig } from '../adapter'
import type { BarProps } from '../types'
import { ChartCanvas } from './ChartCanvas'

/** A bar chart — vertical or horizontal, stacked or grouped. */
export function Bar(props: BarProps): JSX.Element {
    const config = useMemo(() => buildBarConfig(props), [JSON.stringify(props)])
    return <ChartCanvas config={config} {...props} />
}
