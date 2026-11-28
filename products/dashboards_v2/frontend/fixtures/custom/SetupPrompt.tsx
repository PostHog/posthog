import { router } from 'kea-router'

import { Button, Callout, CalloutActions, CalloutContent, CalloutDescription, CalloutTitle } from '@posthog/quill'

import { urls } from 'scenes/urls'

// TODO(2026-11-26): Delete with the kitchen sink fixture, once a product renders its own custom content in a dashboard.
export function SetupPrompt(): JSX.Element {
    return (
        <Callout tone="info">
            <CalloutContent>
                <CalloutTitle>Connect a data source</CalloutTitle>
                <CalloutDescription>Import ad spend and revenue to see them next to your events.</CalloutDescription>
            </CalloutContent>
            <CalloutActions>
                <Button
                    variant="outline"
                    data-attr="dashboard-v2-example-browse-sources"
                    onClick={() => router.actions.push(urls.dataPipelinesNew('source'))}
                >
                    Browse sources
                </Button>
            </CalloutActions>
        </Callout>
    )
}
