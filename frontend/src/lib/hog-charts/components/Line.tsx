import { useMemo } from 'react'

import { buildLineConfig } from '../adapters'
import type { LineProps } from '../types'
import { ChartCanvas } from './ChartCanvas'

export function Line(props: LineProps): JSX.Element {
    const config = useMemo(() => buildLineConfig(props), [JSON.stringify(props)])
    return <ChartCanvas config={config} {...props} />
}
