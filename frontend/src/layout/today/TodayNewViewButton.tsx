import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { NewViewMenu } from 'scenes/views/NewViewMenu'

export function TodayNewViewButton(): JSX.Element {
    return (
        <NewViewMenu
            trigger={
                <Button
                    size="icon"
                    className="-me-2 text-muted-foreground"
                    aria-label="New view"
                    data-attr="today-new-view-header"
                />
            }
        >
            <IconPlus />
        </NewViewMenu>
    )
}
