import { useWindowSize } from 'lib/hooks/useWindowSize'
import React from 'react'

import { LemonSegmentedButton, LemonSegmentedButtonProps } from '../LemonSegmentedButton'
import { LemonSelect, LemonSelectProps } from '../LemonSelect'

export type LemonSegmentedSelectProps<T extends React.Key> = LemonSegmentedButtonProps<T> &
    LemonSelectProps<T> & {
        shrinkOn?: number
    }

export function LemonSegmentedSelect<T extends React.Key>({
    shrinkOn,
    ...props
}: LemonSegmentedSelectProps<T>): JSX.Element {
    const {
        windowSize: { width = 0 },
    } = useWindowSize()

    if ((shrinkOn != null && props.options.length >= shrinkOn) || width < props.options.length * 100) {
        return <LemonSelect {...props} />
    }

    return <LemonSegmentedButton {...props} />
}
