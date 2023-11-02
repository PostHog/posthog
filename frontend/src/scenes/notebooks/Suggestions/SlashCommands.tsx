import { LemonButtonWithDropdown } from '@posthog/lemon-ui'
import { IconPlus } from 'lib/lemon-ui/icons'
import { SlashCommands } from '../Notebook/SlashCommands'
import { InsertionSuggestion, InsertionSuggestionViewProps } from './InsertionSuggestion'

const Component = (props: InsertionSuggestionViewProps): JSX.Element => {
    const handleOnClick = (): void => props.editor?.focus()

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
            onClick={handleOnClick}
            className="NotebookFloatingButton__plus ml-1"
        />
    )
}

export default InsertionSuggestion.create({
    shouldShow: true,
    Component,
})
