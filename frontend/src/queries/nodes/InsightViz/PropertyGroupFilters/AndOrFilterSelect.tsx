import { LemonButtonProps } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { FilterLogicalOperator } from '~/types'

import { LemonAndOrFilterSelect } from './LemonAndOrFilterSelect'
import { QuillAndOrFilterSelect } from './QuillAndOrFilterSelect'

export interface AndOrFilterSelectProps {
    onChange: (type: FilterLogicalOperator) => void
    value: FilterLogicalOperator
    topLevelFilter?: boolean
    prefix?: React.ReactNode
    suffix?: [singular: string, plural: string]
    /** Shown instead of `suffix` in a narrow editor panel. Needs an `editor-panel` container ancestor */
    shortSuffix?: string
    disabledReason?: LemonButtonProps['disabledReason']
    size?: LemonButtonProps['size']
}

export function AndOrFilterSelect(props: AndOrFilterSelectProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? (
        <QuillAndOrFilterSelect
            value={props.value}
            onChange={props.onChange}
            prefix={props.prefix}
            suffix={props.suffix}
            shortSuffix={props.shortSuffix}
            disabledReason={props.disabledReason}
        />
    ) : (
        <LemonAndOrFilterSelect {...props} />
    )
}
