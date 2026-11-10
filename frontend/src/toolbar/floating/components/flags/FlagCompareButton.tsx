import { useActions, useValues } from 'kea'

import { IconCamera } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { flagComparisonLogic } from '~/toolbar/shared/flags/flagComparisonLogic'
import type { FlagInfo } from '~/toolbar/shared/flags/flagInfo'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'

export interface FlagCompareButtonProps {
    flag: FlagInfo
    disabledReason: string | null
}

export function FlagCompareButton({ flag, disabledReason }: FlagCompareButtonProps): JSX.Element {
    const { posthog } = useValues(toolbarConfigLogic)
    const { comparingFlagKey } = useValues(flagComparisonLogic)
    const { compareFlag } = useActions(flagComparisonLogic)
    const isComparing = comparingFlagKey === flag.key

    return (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconCamera />}
            onClick={() => compareFlag(flag)}
            loading={isComparing}
            disabledReason={
                isComparing ? null : (disabledReason ?? (posthog ? null : 'The page has no PostHog client'))
            }
            tooltip="Compare the page with this flag off and on"
            data-attr="toolbar-flag-compare"
        />
    )
}
