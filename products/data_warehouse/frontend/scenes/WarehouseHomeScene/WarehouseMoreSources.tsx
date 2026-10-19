import posthog from 'posthog-js'

import { Button, Card, CardDescription, CardFooter, CardHeader, CardTitle } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseMoreSources(): JSX.Element {
    // The in-app Wizard page is still behind a flag, so everyone else gets the docs.
    const wizardUiEnabled = useFeatureFlag('WIZARD_UI_ENABLED')

    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>Got a different question?</CardTitle>
                <CardDescription>
                    There are hundreds of sources, including payments, CRMs, support desks, ad platforms and your
                    production database, so your question is likely answerable already.
                </CardDescription>
            </CardHeader>
            <CardFooter className="flex-wrap gap-2">
                <Button
                    size="sm"
                    variant="primary"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.dataWarehouseSourceNew()} />}
                    data-attr="warehouse-home-more-sources"
                    onClick={() => posthog.capture('warehouse getting started clicked', { target: 'more_sources' })}
                >
                    Browse sources
                </Button>
                <Button
                    size="sm"
                    nativeButton={false}
                    render={
                        wizardUiEnabled ? (
                            <LinkPrimitive to={urls.wizardRuns()} />
                        ) : (
                            <LinkPrimitive to="https://posthog.com/docs/ai-engineering/ai-wizard" target="_blank" />
                        )
                    }
                    data-attr="warehouse-home-more-wizard"
                    onClick={() => posthog.capture('warehouse getting started clicked', { target: 'more_wizard' })}
                >
                    Wizard setup
                </Button>
            </CardFooter>
        </Card>
    )
}
