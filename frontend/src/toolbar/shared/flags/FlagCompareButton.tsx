import { IconCamera } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface FlagCompareButtonProps {
    comparing: boolean
    disabledReason: string | null
    onCompare: () => void
    dataAttr: string
}

export function FlagCompareButton({
    comparing,
    disabledReason,
    onCompare,
    dataAttr,
}: FlagCompareButtonProps): JSX.Element {
    return (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconCamera />}
            onClick={onCompare}
            loading={comparing}
            disabledReason={comparing ? null : disabledReason}
            tooltip="Compare the page with this flag off and on"
            data-attr={dataAttr}
        />
    )
}
