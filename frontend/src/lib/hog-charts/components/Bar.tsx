import { useMemo } from 'react'

import { buildBarConfig } from '../adapter'
import type { BarProps } from '../types'
import { ChartCanvas } from './ChartCanvas'

export function Bar(props: BarProps): JSX.Element {
    const config = useMemo(() => buildBarConfig(props), [JSON.stringify(props)])
    return <ChartCanvas config={config} {...props} />
}
