import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { analyticsShareLogic } from './analyticsShareLogic'

/** The path to the collection or folder the picker has open, with each level a step back. */
export function ShareToSpaceBreadcrumbs(): JSX.Element {
    const { browseCrumbs } = useValues(analyticsShareLogic)
    const { browseTo } = useActions(analyticsShareLogic)

    return (
        <nav aria-label="Location" className="-mb-1 flex flex-wrap items-center gap-1 text-sm">
            <Button
                variant="link-muted"
                size="sm"
                className="-ml-2"
                onClick={() => browseTo(null)}
                data-attr="analytics-share-crumb-root"
            >
                All collections
            </Button>
            {browseCrumbs.map((crumb, index) => (
                <span key={crumb.path} className="flex items-center gap-1">
                    <IconChevronRight className="size-3 text-muted-foreground" aria-hidden />
                    {index === browseCrumbs.length - 1 ? (
                        <Text size="sm" className="px-2 font-semibold">
                            {crumb.name}
                        </Text>
                    ) : (
                        <Button
                            variant="link-muted"
                            size="sm"
                            onClick={() => browseTo(crumb.path)}
                            data-attr="analytics-share-crumb"
                        >
                            {crumb.name}
                        </Button>
                    )}
                </span>
            ))}
        </nav>
    )
}
