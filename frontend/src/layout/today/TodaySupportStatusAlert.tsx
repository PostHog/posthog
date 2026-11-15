import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Button, Item, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { incidentStatusLogic } from 'lib/components/HelpMenu/incidentStatusLogic'

export function TodaySupportStatusAlert(): JSX.Element | null {
    const { status, statusDescription, statusPageUrl } = useValues(incidentStatusLogic)

    if (status === 'operational') {
        return null
    }

    return (
        <Item variant="outline" tone={status.includes('outage') ? 'destructive' : 'warning'}>
            <ItemMedia variant="icon">
                <IconWarning />
            </ItemMedia>
            <ItemContent>
                <ItemTitle>{statusDescription || 'Active incident'}</ItemTitle>
                <ItemDescription>
                    We're aware of an issue that may be affecting your PostHog experience. You may wish to check our
                    current status before contacting support.
                </ItemDescription>
                <Button
                    variant="link"
                    size="sm"
                    className="self-start p-0"
                    render={
                        // eslint-disable-next-line react/forbid-elements
                        <a href={statusPageUrl} target="_blank" rel="noopener noreferrer" />
                    }
                >
                    View current status
                </Button>
            </ItemContent>
        </Item>
    )
}
