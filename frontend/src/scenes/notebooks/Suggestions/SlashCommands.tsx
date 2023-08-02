import { LemonButtonWithDropdown } from '@posthog/lemon-ui'
import { IconPlus } from 'lib/lemon-ui/icons'
import { SlashCommands } from '../Notebook/SlashCommands'
import { InsertionSuggestion } from './InsertionSuggestion'

const Component = (): JSX.Element => {
    return (
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
            className="NotebookFloatingButton__plus ml-1"
        />
    )
}

export default InsertionSuggestion.create({
    shouldShow: true,
    Component,
})
