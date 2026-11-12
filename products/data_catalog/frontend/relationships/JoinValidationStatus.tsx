import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import {
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Spinner,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { openInAppSupport } from 'lib/components/Support/openInAppSupport'

import { viewLinkLogic } from 'products/data_warehouse/frontend/shared/logics/viewLinkLogic'

const MATCH_COLUMN_TITLES: Record<string, string> = {
    source_key: 'Source key',
    joining_key: 'Joining key',
}

function Callout({ tone, children }: { tone: 'warning' | 'destructive'; children: React.ReactNode }): JSX.Element {
    return (
        <Item variant="outline" tone={tone} size="sm">
            <ItemContent>
                <ItemDescription>{children}</ItemDescription>
            </ItemContent>
        </Item>
    )
}

function JoinMatchPreview(): JSX.Element | null {
    const { joinValidation } = useValues(viewLinkLogic)
    const response = joinValidation.response
    if (joinValidation.status !== 'valid' || !response) {
        return null
    }
    const columns = response.columns ?? []

    return (
        <div className="flex flex-col gap-2">
            {response.match_rate != null && response.total_rows != null && (
                <Text size="xs" variant="muted">
                    {`${Math.round(response.match_rate * 100)}% of ${response.total_rows.toLocaleString()} sampled rows matched`}
                </Text>
            )}
            {columns.length > 0 && response.results.length > 0 && (
                <Table size="sm" fullWidth>
                    <TableHeader>
                        <TableRow>
                            {columns.map((column) => (
                                <TableHead key={column}>{MATCH_COLUMN_TITLES[column] ?? column}</TableHead>
                            ))}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {response.results.map((row: unknown[], rowIndex: number) => (
                            <TableRow key={rowIndex}>
                                {columns.map((column, columnIndex) => (
                                    <TableCell key={column} className="font-mono text-xs">
                                        {String(row[columnIndex] ?? '')}
                                    </TableCell>
                                ))}
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            )}
        </div>
    )
}

export function JoinValidationStatus(): JSX.Element {
    const { joinValidation, keyTypeMismatchWarning } = useValues(viewLinkLogic)

    return (
        <div className="flex flex-col gap-2 empty:hidden">
            {keyTypeMismatchWarning && <Callout tone="warning">{keyTypeMismatchWarning}</Callout>}
            {joinValidation.status === 'validating' && (
                <Text size="xs" variant="muted" className="flex items-center gap-2">
                    <Spinner />
                    Validating join...
                </Text>
            )}
            {joinValidation.status === 'valid' && (
                <>
                    <Text size="xs" className="flex items-center gap-2 text-success-foreground">
                        <IconCheckCircle />
                        Join is valid
                    </Text>
                    <JoinMatchPreview />
                </>
            )}
            {joinValidation.status === 'valid' && joinValidation.msg && (
                <Callout tone="warning">{joinValidation.msg}</Callout>
            )}
            {joinValidation.status === 'error' && (
                <Item variant="outline" tone="destructive" size="sm">
                    <ItemContent>
                        <ItemDescription>{joinValidation.msg || 'Could not validate the join.'}</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => openInAppSupport('join-modal-validation-error')}
                        >
                            Get help
                        </Button>
                    </ItemActions>
                </Item>
            )}
        </div>
    )
}
