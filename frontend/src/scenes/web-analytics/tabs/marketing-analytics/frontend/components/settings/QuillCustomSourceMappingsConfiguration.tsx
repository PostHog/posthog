import { IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    Chip,
    ChipClose,
    Heading,
    Input,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { MARKETING_DEFAULT_SOURCE_MAPPINGS } from '~/queries/schema/schema-general'

export function QuillCustomSourceMappingsConfiguration({
    sourceFilter,
    integrationsToShow,
    customMappings,
    getInputValue,
    onInputChange,
    getValidationError,
    onAddMapping,
    onRemoveMapping,
    restrictedReason,
}: {
    sourceFilter?: string
    integrationsToShow: string[]
    customMappings: Record<string, string[]>
    getInputValue: (integration: string) => string
    onInputChange: (integration: string, value: string) => void
    getValidationError: (integration: string) => string | null
    onAddMapping: (integration: string) => void
    onRemoveMapping: (integration: string, utmSource: string) => void
    restrictedReason: string | null
}): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            {!sourceFilter && (
                <>
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Custom UTM source mappings
                    </Heading>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Add custom <code>utm_source</code> values to attribute conversions to your ad platforms. Default
                        sources are shown but cannot be removed.
                    </Text>
                </>
            )}

            <Table>
                <TableHeader>
                    <TableRow>
                        {!sourceFilter && <TableHead>Integration</TableHead>}
                        <TableHead>UTM sources</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {integrationsToShow.map((integration) => {
                        const defaults =
                            MARKETING_DEFAULT_SOURCE_MAPPINGS[
                                integration as keyof typeof MARKETING_DEFAULT_SOURCE_MAPPINGS
                            ] || []
                        const custom = customMappings[integration] || []
                        const validationError = getValidationError(integration)

                        return (
                            <TableRow key={integration}>
                                {!sourceFilter && (
                                    <TableCell className="align-top font-medium">{integration}</TableCell>
                                )}
                                <TableCell className="whitespace-normal">
                                    <div className="flex flex-wrap items-center gap-1">
                                        {defaults.map((source) => (
                                            <Badge key={source}>{source}</Badge>
                                        ))}
                                        {custom.map((source) => (
                                            <Chip key={source}>
                                                {source}
                                                <ChipClose
                                                    aria-label={`Remove ${source}`}
                                                    onClick={() => onRemoveMapping(integration, source)}
                                                />
                                            </Chip>
                                        ))}
                                        <div className="flex items-center gap-1">
                                            <Input
                                                size="sm"
                                                className="w-40"
                                                aria-label={`Add custom sources for ${integration}`}
                                                value={getInputValue(integration)}
                                                onChange={(event) => onInputChange(integration, event.target.value)}
                                                placeholder="Add custom sources"
                                                disabledReason={restrictedReason}
                                            />
                                            <Button
                                                size="icon-sm"
                                                variant="primary"
                                                aria-label="Add custom sources"
                                                tooltip={!validationError ? 'Add custom sources' : undefined}
                                                onClick={() => onAddMapping(integration)}
                                                disabledReason={validationError || restrictedReason}
                                            >
                                                <IconPlus />
                                            </Button>
                                        </div>
                                    </div>
                                </TableCell>
                            </TableRow>
                        )
                    })}
                </TableBody>
            </Table>
        </section>
    )
}
