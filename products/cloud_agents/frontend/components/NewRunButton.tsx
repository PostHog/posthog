import { useActions } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cloudAgentsNewRunLogic } from '../logics/cloudAgentsNewRunLogic'

export function NewRunButton({ label = 'New run' }: { label?: string }): JSX.Element {
    const { openNewRunModal } = useActions(cloudAgentsNewRunLogic)
    return (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconPlusSmall />}
            onClick={openNewRunModal}
            data-attr="cloud-agents-new-run"
        >
            {label}
        </LemonButton>
    )
}
