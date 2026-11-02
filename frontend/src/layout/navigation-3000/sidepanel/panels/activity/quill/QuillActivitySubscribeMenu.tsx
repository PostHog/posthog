import { combineUrl, router } from 'kea-router'

import { IconBell } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { HOG_FUNCTION_SUB_TEMPLATES } from 'scenes/hog-functions/sub-templates/sub-templates'
import { urls } from 'scenes/urls'

import { CyclotronJobFilterPropertyFilter } from '~/types'

interface QuillActivitySubscribeMenuProps {
    properties: CyclotronJobFilterPropertyFilter[]
    onNavigate?: () => void
}

export function QuillActivitySubscribeMenu({ properties, onNavigate }: QuillActivitySubscribeMenuProps): JSX.Element {
    const go = (url: string): void => {
        onNavigate?.()
        router.actions.push(url)
    }

    return (
        <DropdownMenu>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <DropdownMenuTrigger render={<Button variant="outline" size="icon" aria-label="Subscribe" />} />
                    }
                >
                    <IconBell />
                </TooltipTrigger>
                <TooltipContent>Subscribe</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" className="w-60">
                <DropdownMenuGroup>
                    {HOG_FUNCTION_SUB_TEMPLATES['activity-log'].map((subTemplate) => {
                        const filters = {
                            events: subTemplate.filters?.events || [
                                { id: '$activity_log_entry_created', type: 'events' as const },
                            ],
                            properties,
                        }
                        const configuration = { ...subTemplate, filters }
                        return (
                            <DropdownMenuItem
                                key={subTemplate.template_id + (subTemplate.name ?? '')}
                                onClick={() =>
                                    go(
                                        combineUrl(urls.hogFunctionNew(subTemplate.template_id), {}, { configuration })
                                            .url
                                    )
                                }
                            >
                                {subTemplate.name || 'Subscribe'}
                            </DropdownMenuItem>
                        )
                    })}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    onClick={() => go(urls.settings('environment-activity-logs', 'activity-log-notifications'))}
                >
                    View all notifications
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
