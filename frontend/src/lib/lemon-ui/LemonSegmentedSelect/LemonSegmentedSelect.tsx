import { Key } from 'react'

import { useWindowSize } from 'lib/hooks/useWindowSize'

import { LemonSegmentedButton, LemonSegmentedButtonProps } from '../LemonSegmentedButton'
import { LemonSelect, LemonSelectProps } from '../LemonSelect'

type LemonSelectKey = string | number | boolean | null

export type LemonSegmentedSelectProps<T extends LemonSelectKey> = LemonSegmentedButtonProps<T & Key> &
    LemonSelectProps<T> & {
        shrinkOn?: number
    }

export function LemonSegmentedSelect<T extends LemonSelectKey>({
    shrinkOn,
    ...props
}: LemonSegmentedSelectProps<T>): JSX.Element {
    const {
        windowSize: { width = 0 },
    } = useWindowSize()

    if ((shrinkOn != null && props.options.length >= shrinkOn) || width < props.options.length * 100) {
        return <LemonSelect {...props} />
    }

    return <LemonSegmentedButton {...(props as unknown as LemonSegmentedButtonProps<T & Key>)} />
}
