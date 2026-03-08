import { useMemo } from 'react'

import { buildAreaConfig } from '../adapter'
import type { AreaProps } from '../types'
import { ChartCanvas } from './ChartCanvas'

export function Area(props: AreaProps): JSX.Element {
    const config = useMemo(() => buildAreaConfig(props), [JSON.stringify(props)])
    return <ChartCanvas config={config} {...props} />
}
