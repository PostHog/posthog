import { useMemo } from 'react'

import { buildPieConfig } from '../adapters'
import type { PieProps } from '../types'
import { ChartCanvas } from './ChartCanvas'

export function Pie(props: PieProps): JSX.Element {
    const config = useMemo(() => buildPieConfig(props), [JSON.stringify(props)])
    return <ChartCanvas config={config} {...props} />
}
