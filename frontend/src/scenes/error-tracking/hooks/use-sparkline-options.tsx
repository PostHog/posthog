import { useValues } from 'kea'
import { useMemo } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { SparklineOptions } from '../components/SparklineChart/SparklineChart'

const GRAY_700 = 'primitive-neutral-700'
const GRAY_200 = 'primitive-neutral-200'

export function useSparklineOptions(overrides: Partial<SparklineOptions> = {}, deps: any[] = []): SparklineOptions {
    const colorVars = useDefaultSparklineColorVars()
    return useMemo(() => {
        return {
            backgroundColor: `var(--${colorVars[0]})`,
            hoverBackgroundColor: `var(--${colorVars[1]})`,
            axisColor: `var(--${colorVars[0]})`,
            borderRadius: 5,
            eventLabelHeight: 20,
            eventLabelPaddingX: 5,
            eventLabelPaddingY: 3,
            eventMinSpace: 2,
            ...overrides,
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [colorVars, ...deps])
}

export function useDefaultSparklineColorVars(): [string, string] {
    const { isDarkModeOn } = useValues(themeLogic)
    const colors = useMemo(() => [GRAY_200, GRAY_700], [])
    return useMemo(() => (isDarkModeOn ? [...colors].reverse() : colors), [isDarkModeOn, colors]) as [string, string]
}
