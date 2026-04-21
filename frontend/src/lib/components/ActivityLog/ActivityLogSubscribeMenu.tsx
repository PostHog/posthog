import { combineUrl, router } from 'kea-router'

import { IconBell } from '@posthog/icons'
import { LemonButton, LemonMenu, Tooltip } from '@posthog/lemon-ui'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { HOG_FUNCTION_SUB_TEMPLATES } from 'scenes/hog-functions/sub-templates/sub-templates'
import { urls } from 'scenes/urls'

import { CyclotronJobFilterPropertyFilter } from '~/types'

export interface ActivityLogSubscribeMenuProps {
    properties: CyclotronJobFilterPropertyFilter[]
    onNavigate?: () => void
    tooltip?: string
    disabledReason?: string
    'data-attr'?: string
}

export function ActivityLogSubscribeMenu({
    properties,
    onNavigate,
    tooltip,
    disabledReason,
    'data-attr': dataAttr,
}: ActivityLogSubscribeMenuProps): JSX.Element {
    const templateItems = HOG_FUNCTION_SUB_TEMPLATES['activity-log'].map((subTemplate) => {
        const filters = {
            events: subTemplate.filters?.events || [{ id: '$activity_log_entry_created', type: 'events' as const }],
            properties,
        }
        const configuration = { ...subTemplate, filters }
        const url = combineUrl(urls.hogFunctionNew(subTemplate.template_id), {}, { configuration }).url
        return {
            label: subTemplate.name || 'Subscribe',
            onClick: () => {
                onNavigate?.()
                router.actions.push(url)
            },
        }
    })

    const items = [
        { items: templateItems },
        {
            items: [
                {
                    label: 'View all notifications',
                    onClick: () => {
                        onNavigate?.()
                        router.actions.push(urls.settings('environment-activity-logs', 'activity-log-notifications'))
                    },
                },
            ],
        },
    ] as LemonMenuItems

    const trigger = (
        <LemonButton
            size="small"
            type="secondary"
            icon={<IconBell />}
            tooltip={tooltip ?? 'Subscribe'}
            disabledReason={disabledReason}
            data-attr={dataAttr}
        >
            Subscribe
        </LemonButton>
    )

    if (disabledReason) {
        return <Tooltip title={disabledReason}>{trigger}</Tooltip>
    }

    return (
        <LemonMenu placement="bottom-end" items={items}>
            {trigger}
        </LemonMenu>
    )
}
