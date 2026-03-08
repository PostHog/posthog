import { useMemo } from 'react'

import { buildLifecycleConfig } from '../adapters'
import type { LifecycleProps } from '../types'
import { ChartCanvas } from './ChartCanvas'

export function Lifecycle(props: LifecycleProps): JSX.Element {
    const config = useMemo(() => buildLifecycleConfig(props), [JSON.stringify(props)])
    return <ChartCanvas config={config} {...props} />
}
