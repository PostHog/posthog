import { Skeleton, Text } from '@posthog/quill'

import { IntegrationView } from 'lib/integrations/IntegrationView'

import { IntegrationType } from '~/types'

export function QuillIntegrationsList({
    titleText,
    integrations,
    loading,
    emptyState,
    renderActions,
}: {
    titleText: string
    integrations: IntegrationType[] | undefined
    loading: boolean
    emptyState?: JSX.Element
    renderActions?: (integration: IntegrationType) => JSX.Element | null
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {titleText ? (
                <Text size="xs" render={<p className="m-0" />}>
                    {titleText}
                </Text>
            ) : null}

            {integrations?.length ? (
                integrations.map((integration) => (
                    <IntegrationView
                        key={integration.id}
                        integration={integration}
                        actions={renderActions?.(integration)}
                    />
                ))
            ) : loading ? (
                <Skeleton className="h-10" />
            ) : (
                emptyState
            )}
        </div>
    )
}
