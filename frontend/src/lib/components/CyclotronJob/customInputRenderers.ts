import { ComponentType, lazy } from 'react'

import { CyclotronJobInputSchemaType } from '~/types'

export interface CustomInputRendererProps {
    schema: CyclotronJobInputSchemaType
    value: any
    onChange: (value: any) => void
}

export const CUSTOM_INPUT_RENDERERS: Record<
    string,
    React.LazyExoticComponent<ComponentType<CustomInputRendererProps>>
> = {
    posthog_assignee: lazy(
        () => import('products/conversations/frontend/components/Assignee/CyclotronJobInputAssignee')
    ),
    posthog_ticket_tags: lazy(
        () => import('products/conversations/frontend/components/TicketTags/CyclotronJobInputTicketTags')
    ),
}
