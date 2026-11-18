import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconWarning } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
    Text,
} from '@posthog/quill'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { urls } from 'scenes/urls'

import { parseErrorMessage } from '~/queries/query'

import { METRIC_ERROR_TITLE, METRIC_TIMEOUT_MESSAGE, METRIC_TIMEOUT_TITLE } from './MetricErrorState'

export function QuillMetricErrorState({
    error,
    query,
    onRetry,
    retryDisabledReason,
}: {
    error: { detail: string | object | any; statusCode?: number; queryId?: string }
    query?: Record<string, any>
    onRetry?: () => void
    retryDisabledReason?: string
}): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)
    const isTimeout = error.statusCode === 504
    const { message } = parseErrorMessage(error.detail)

    return (
        <Empty className="border-none">
            <EmptyHeader>
                <IconStack>
                    <IconStackItem color="var(--color-product-experiments-light)">
                        <IconWarning />
                    </IconStackItem>
                </IconStack>
                <EmptyTitle>{isTimeout ? METRIC_TIMEOUT_TITLE : METRIC_ERROR_TITLE}</EmptyTitle>
                <EmptyDescription>{isTimeout ? METRIC_TIMEOUT_MESSAGE : message}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="flex-row flex-wrap justify-center">
                {onRetry &&
                    (query ? (
                        <ButtonGroup>
                            <Button variant="primary" onClick={onRetry} disabledReason={retryDisabledReason}>
                                Try again
                            </Button>
                            <DropdownMenu>
                                <DropdownMenuTrigger
                                    render={
                                        <Button
                                            variant="primary"
                                            size="icon"
                                            aria-label="More retry options"
                                            tooltip="More retry options"
                                        />
                                    }
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
                    ) : (
                        <Button variant="primary" onClick={onRetry} disabledReason={retryDisabledReason}>
                            Try again
                        </Button>
                    ))}
                <Button variant="outline" onClick={() => openSupportForm({ kind: 'bug' })}>
                    Report issue
                </Button>
            </EmptyContent>
            {error.queryId && (
                <Text size="xxs" variant="muted">
                    Query ID: <span className="font-mono">{error.queryId}</span>
                </Text>
            )}
        </Empty>
    )
}
