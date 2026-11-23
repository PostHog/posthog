import { IconInfo, IconPlus, IconTrash, IconWarning } from '@posthog/icons'
import {
    Button,
    Chip,
    ChipClose,
    Field,
    Heading,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Textarea,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { MatchField } from '~/queries/schema/schema-general'

import { QuillMappingCombobox, QuillMappingOption } from './QuillMappingCombobox'
import { CampaignSuggestion } from './stringSimilarity'

export function QuillCampaignNameMappingsConfiguration({
    sourceFilter,
    compact,
    filteredMappings,
    columnHeader,
    matchField,
    campaigns,
    campaignOptions,
    campaignsLoading,
    availableSources,
    selectedSource,
    onSelectedSourceChange,
    newCleanName,
    onNewCleanNameChange,
    newRawValues,
    onNewRawValuesChange,
    campaignSuggestions,
    alreadyMappedValues,
    cannotAddMapping,
    onAddMapping,
    onRemoveUtmValue,
    onRemoveMapping,
    restrictedReason,
}: {
    sourceFilter?: string
    compact: boolean
    filteredMappings: Record<string, Record<string, string[]> | undefined>
    columnHeader: string
    matchField: MatchField
    campaigns: { id: string; name: string }[]
    campaignOptions: QuillMappingOption[]
    campaignsLoading: boolean
    availableSources: readonly string[]
    selectedSource: string
    onSelectedSourceChange: (source: string) => void
    newCleanName: string
    onNewCleanNameChange: (name: string) => void
    newRawValues: string
    onNewRawValuesChange: (values: string) => void
    campaignSuggestions: CampaignSuggestion[]
    alreadyMappedValues: Array<{ value: string; integration: string; campaignName: string }>
    cannotAddMapping: boolean
    onAddMapping: () => void
    onRemoveUtmValue: (source: string, cleanName: string, utmValue: string) => void
    onRemoveMapping: (source: string, cleanName: string) => void
    restrictedReason: string | null
}): JSX.Element {
    const mappingRows = Object.entries(filteredMappings).flatMap(([source, sourceMappings]) =>
        sourceMappings
            ? Object.entries(sourceMappings).map(([cleanName, rawValues]) => ({ source, cleanName, rawValues }))
            : []
    )
    const hasAlreadyMappedValues = alreadyMappedValues.length > 0
    const matchedCampaign =
        matchField === MatchField.CAMPAIGN_ID
            ? campaigns.find((c) => c.id === newCleanName)
            : campaigns.find((c) => c.name === newCleanName)

    return (
        <section className="flex flex-col gap-3">
            {compact ? (
                <Heading size="sm" render={<h4 className="m-0" />}>
                    Campaign name mappings
                </Heading>
            ) : (
                <div className="flex flex-col gap-1">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Campaign name mappings
                    </Heading>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Map UTM campaign values to your ad platform campaign names for proper conversion attribution. If
                        your <code>utm_campaign</code> doesn't exactly match your ad platform campaign name, your
                        conversions won't attribute to the paid campaign.
                    </Text>
                </div>
            )}

            {mappingRows.length > 0 && (
                <Table>
                    <TableHeader>
                        <TableRow>
                            {!sourceFilter && <TableHead>Source</TableHead>}
                            <TableHead>{columnHeader}</TableHead>
                            <TableHead>utm_campaign</TableHead>
                            <TableHead className="text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {mappingRows.map(({ source, cleanName, rawValues }) => (
                            <TableRow key={`${source}-${cleanName}`}>
                                {!sourceFilter && <TableCell className="align-top">{source}</TableCell>}
                                <TableCell className="align-top font-medium">{cleanName}</TableCell>
                                <TableCell className="whitespace-normal">
                                    <div className="flex flex-wrap gap-1">
                                        {rawValues.map((rawValue) => (
                                            <Chip key={rawValue}>
                                                {rawValue}
                                                <ChipClose
                                                    aria-label={`Remove ${rawValue}`}
                                                    onClick={() => onRemoveUtmValue(source, cleanName, rawValue)}
                                                />
                                            </Chip>
                                        ))}
                                    </div>
                                </TableCell>
                                <TableCell className="align-top text-right">
                                    <Button
                                        size="icon-sm"
                                        variant="destructive-outline"
                                        aria-label="Remove mapping"
                                        tooltip="Remove mapping"
                                        onClick={() => onRemoveMapping(source, cleanName)}
                                        disabledReason={restrictedReason}
                                    >
                                        <IconTrash />
                                    </Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            )}

            <div className="flex flex-wrap items-start gap-2">
                {!sourceFilter && (
                    <Field className="w-40">
                        <Select
                            value={selectedSource || null}
                            onValueChange={(next) => onSelectedSourceChange((next as string | null) ?? '')}
                        >
                            <SelectTrigger aria-label="Source" disabledReason={restrictedReason}>
                                <SelectValue placeholder="Source..." />
                            </SelectTrigger>
                            <SelectContent>
                                {availableSources.map((source) => (
                                    <SelectItem key={source} value={source}>
                                        {source}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </Field>
                )}

                <Field className="min-w-50 flex-1">
                    <QuillMappingCombobox
                        value={newCleanName || null}
                        onChange={(value) => onNewCleanNameChange(value || '')}
                        options={campaignOptions}
                        placeholder={columnHeader}
                        loading={campaignsLoading}
                        disabledReason={restrictedReason}
                        ariaLabel={columnHeader}
                        className="w-full"
                    />
                    {newCleanName && (
                        <Text size="xs" variant="muted" render={<div className="flex flex-col break-all" />}>
                            {matchField === MatchField.CAMPAIGN_ID ? (
                                <>
                                    <span>{`ID: ${newCleanName}`}</span>
                                    <span>{`Name: ${matchedCampaign?.name || '(custom)'}`}</span>
                                </>
                            ) : (
                                <>
                                    <span>{`Name: ${newCleanName}`}</span>
                                    <span>{`ID: ${matchedCampaign?.id || '(custom)'}`}</span>
                                </>
                            )}
                        </Text>
                    )}
                    {campaignSuggestions.length > 0 && (
                        <div className="flex flex-col gap-1">
                            <div className="flex items-center gap-1">
                                <Text size="xs" variant="muted" render={<span />}>
                                    Suggested matches:
                                </Text>
                                <Tooltip>
                                    <TooltipTrigger
                                        delay={0}
                                        render={<Button size="icon-xs" aria-label="About suggested matches" />}
                                    >
                                        <IconInfo />
                                    </TooltipTrigger>
                                    <TooltipContent className="max-w-80">
                                        Suggestions are based on string similarity (Levenshtein distance) between your
                                        utm_campaign value and campaign names from the integration.
                                    </TooltipContent>
                                </Tooltip>
                            </div>
                            <div className="flex flex-wrap gap-1">
                                {campaignSuggestions.map((suggestion) => (
                                    <Button
                                        key={suggestion.id}
                                        variant="outline"
                                        onClick={() =>
                                            onNewCleanNameChange(
                                                matchField === MatchField.CAMPAIGN_ID ? suggestion.id : suggestion.name
                                            )
                                        }
                                        tooltip={
                                            matchField === MatchField.CAMPAIGN_ID
                                                ? `${suggestion.name} (${Math.round(suggestion.score * 100)}% match)`
                                                : `ID: ${suggestion.id} (${Math.round(suggestion.score * 100)}% match)`
                                        }
                                        disabledReason={restrictedReason}
                                    >
                                        {matchField === MatchField.CAMPAIGN_ID
                                            ? `${suggestion.id} (${suggestion.name})`
                                            : `${suggestion.name} (${suggestion.id})`}
                                    </Button>
                                ))}
                            </div>
                        </div>
                    )}
                </Field>

                <Field className="min-w-50 flex-1">
                    <Textarea
                        aria-label="utm_campaign values"
                        value={newRawValues}
                        onChange={(event) => onNewRawValuesChange(event.target.value)}
                        placeholder="utm_campaign values (comma-separated)"
                        rows={1}
                        disabledReason={restrictedReason}
                    />
                    {hasAlreadyMappedValues && (
                        <Text size="xs" render={<div className="flex items-start gap-1 text-warning-foreground" />}>
                            <IconWarning className="mt-0.5 size-3 shrink-0" />
                            <span>
                                {alreadyMappedValues.length === 1
                                    ? `"${alreadyMappedValues[0].value}" is already mapped to ${alreadyMappedValues[0].integration}: ${alreadyMappedValues[0].campaignName}`
                                    : `${alreadyMappedValues.length} values are already mapped elsewhere`}
                            </span>
                        </Text>
                    )}
                </Field>

                <Button
                    size="icon"
                    variant="primary"
                    aria-label="Add mapping"
                    tooltip="Add mapping"
                    onClick={onAddMapping}
                    disabled={cannotAddMapping}
                    disabledReason={
                        restrictedReason ||
                        (hasAlreadyMappedValues
                            ? 'Some utm_campaign values are already mapped. Each value can only be in one mapping.'
                            : null)
                    }
                >
                    <IconPlus />
                </Button>
            </div>
        </section>
    )
}
