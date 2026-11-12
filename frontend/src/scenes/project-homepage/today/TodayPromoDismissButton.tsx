import { useActions } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { navPanelAdvertisementLogic } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisementLogic'

/** The dismissal is shared with the sidebar card for the same promotion. */
export function TodayPromoDismissButton({
    dismissKey,
    onDismiss,
    dataAttr,
}: {
    dismissKey: string
    onDismiss: () => void
    dataAttr: string
}): JSX.Element {
    const { hideAdvertisement } = useActions(navPanelAdvertisementLogic({ dismissKey }))

    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        variant="link-muted"
                        size="icon-sm"
                        aria-label="Dismiss"
                        onClick={() => {
                            onDismiss()
                            hideAdvertisement()
                        }}
                        data-attr={dataAttr}
                    />
                }
            >
                <IconX className="size-3.5" />
            </TooltipTrigger>
            <TooltipContent side="bottom">Dismiss</TooltipContent>
        </Tooltip>
    )
}
