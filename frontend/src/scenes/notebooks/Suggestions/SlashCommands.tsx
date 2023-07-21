import { LemonButtonWithDropdown } from '@posthog/lemon-ui'
import { IconPlus } from 'lib/lemon-ui/icons'
import { SlashCommands } from '../Notebook/SlashCommands'

const Component = (): React.ReactNode => (
    <LemonButtonWithDropdown
        size="small"
        icon={<IconPlus />}
        dropdown={{
            overlay: <SlashCommands mode="add" range={undefined} />,
            placement: 'right-start',
            fallbackPlacements: ['left-start'],
            actionable: true,
            closeParentPopoverOnClickInside: true,
        }}
    />
)

export default {
    shouldShow: true,
    Component,
}
