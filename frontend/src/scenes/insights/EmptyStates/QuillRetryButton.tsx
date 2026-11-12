import { router } from 'kea-router'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { urls } from 'scenes/urls'

import type { Node } from '~/queries/schema/schema-general'

export function QuillRetryButton({
    onRetry,
    query,
    loading,
    disabledReason,
}: {
    onRetry: () => void
    query?: Record<string, any> | Node | null
    loading: boolean
    disabledReason?: string
}): JSX.Element {
    const retry = (
        <Button
            variant="primary"
            loading={loading}
            disabledReason={disabledReason}
            onClick={() => onRetry()}
            data-attr="insight-retry-button"
        >
            Try again
        </Button>
    )

    if (!query) {
        return retry
    }

    return (
        <ButtonGroup>
            {retry}
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={<Button variant="primary" size="icon" aria-label="More ways to fix this query" />}
                >
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => router.actions.push(urls.debugQuery(query))}>
                        Open in query debugger
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </ButtonGroup>
    )
}
