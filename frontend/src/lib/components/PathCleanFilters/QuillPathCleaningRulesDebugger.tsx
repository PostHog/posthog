import { IconChevronRight } from '@posthog/icons'
import {
    Badge,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Dot,
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill'

import { parseAliasToReadable } from './PathCleanFilterItem'
import type { ProcessingStep } from './PathCleaningRulesDebugger'

export function QuillPathCleaningRulesDebugger({
    debugSteps,
    finalResult,
}: {
    debugSteps: ProcessingStep[]
    finalResult: JSX.Element | JSX.Element[] | string | null
}): JSX.Element {
    return (
        <Collapsible>
            <CollapsibleTrigger>Debug: Step-by-step processing</CollapsibleTrigger>
            <CollapsibleContent className="pt-2">
                <div className="flex flex-col gap-2">
                    <Table fullWidth tableClassName="table-fixed">
                        <TableHeader>
                            <TableRow>
                                <TableHead className="w-10" title="Rule number in processing order">
                                    #
                                </TableHead>
                                <TableHead title="Regex pattern and replacement alias">Pattern → Alias</TableHead>
                                <TableHead title="Path after this rule is applied">Output</TableHead>
                                <TableHead className="w-10" title="Whether this rule matched and modified the path">
                                    ✓
                                </TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {debugSteps.map((step) => (
                                <TableRow key={step.stepNumber}>
                                    <TableCell className="text-muted-foreground">{step.stepNumber}</TableCell>
                                    <TableCell>
                                        <span className="flex min-w-0 items-center gap-2">
                                            <Badge
                                                variant={step.isValidRegex ? 'default' : 'destructive'}
                                                className="max-w-32 shrink-0 font-mono"
                                                title={step.filter.regex || '(Empty)'}
                                            >
                                                <span className="truncate">{step.filter.regex || '(Empty)'}</span>
                                            </Badge>
                                            <IconChevronRight className="size-3 shrink-0 text-muted-foreground" />
                                            <span
                                                className="min-w-0 truncate font-mono"
                                                title={step.filter.alias || '(Empty)'}
                                                translate="no"
                                            >
                                                {parseAliasToReadable(step.filter.alias || '(Empty)')}
                                            </span>
                                        </span>
                                    </TableCell>
                                    <TableCell>
                                        <span
                                            className="block truncate font-mono"
                                            title={step.outputPath}
                                            translate="no"
                                        >
                                            {parseAliasToReadable(step.outputPath)}
                                        </span>
                                    </TableCell>
                                    <TableCell>
                                        {step.wasModified ? (
                                            <Dot
                                                variant="success"
                                                title="Matched and modified"
                                                aria-label="Matched and modified"
                                            />
                                        ) : (
                                            <Dot title="No match, unchanged" aria-label="No match, unchanged" />
                                        )}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemTitle>Final result:</ItemTitle>
                            <ItemDescription>
                                <code
                                    className="block truncate font-mono"
                                    title={
                                        typeof finalResult === 'string' ? finalResult : debugSteps.at(-1)?.outputPath
                                    }
                                    translate="no"
                                >
                                    {finalResult}
                                </code>
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                </div>
            </CollapsibleContent>
        </Collapsible>
    )
}
