import { ComponentType } from 'react'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { CyclotronJobInputSchemaType, CyclotronJobInvocationGlobalsWithInputs } from '~/types'

export interface CustomInputRendererProps {
    schema: CyclotronJobInputSchemaType
    value: any
    onChange: (value: any) => void
    // Hog globals, forwarded for renderers whose values are Hog expressions (e.g. the
    // account-properties editor) so they can offer `{event.*}` autocomplete. Optional — most
    // renderers ignore it.
    sampleGlobalsWithInputs?: CyclotronJobInvocationGlobalsWithInputs | null
}

export const CUSTOM_INPUT_RENDERERS: Record<
    string,
    React.LazyExoticComponent<ComponentType<CustomInputRendererProps>>
> = {
    posthog_assignee: lazyWithRetry(
        () => import('products/conversations/frontend/components/Assignee/CyclotronJobInputAssignee')
    ),
    posthog_ticket_tags: lazyWithRetry(
        () => import('products/conversations/frontend/components/TicketTags/CyclotronJobInputTicketTags')
    ),
    posthog_business_hours: lazyWithRetry(
        () => import('products/conversations/frontend/components/SlaBusinessHours/CyclotronJobInputBusinessHours')
    ),
    customer_analytics_account_properties: lazyWithRetry(
        () =>
            import('products/customer_analytics/frontend/components/AccountPropertiesInput/CyclotronJobInputAccountProperties')
    ),
    customer_analytics_account_relationships: lazy(
        () =>
            import('products/customer_analytics/frontend/components/AccountRelationshipsInput/CyclotronJobInputAccountRelationships')
    ),
}
