import { IconCopy, IconInfo, IconWarning } from '@posthog/icons'
import {
    Button,
    Card,
    DataTable,
    Field,
    FieldDescription,
    FieldLabel,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
} from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import {
    FEATURE_FLAG_SEARCH_MAX_LENGTH,
    FLAGS_PER_PAGE,
    FeatureFlagsFilters,
} from 'scenes/feature-flags/featureFlagsLogic'
import { urls } from 'scenes/urls'

import { FeatureFlagType } from '~/types'

import {
    ExperimentFlagKeyInputProps,
    FLAG_KEY_PLACEHOLDER,
    NO_MATCHING_FLAGS,
    RESET_ANALYSIS_DOCS_URL,
    REUSE_FLAG_LABEL,
    ReuseFlagCopy,
    flagKeyHint,
    flagSelectDisabledReason,
    isOngoingExperiment,
} from './ExperimentFlagKeyInput'

const FLAG_TYPE_OPTIONS: { value: NonNullable<FeatureFlagsFilters['type']> | 'all'; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'boolean', label: 'Boolean' },
    { value: 'multivariant', label: 'Multiple variants' },
    { value: 'experiment', label: 'Experiment' },
    { value: 'remote_config', label: 'Remote config' },
]

type SortingState = NonNullable<DataTableProps<FeatureFlagType, unknown>['sorting']>

function sortingFromOrder(order: string | undefined): SortingState {
    return order ? [{ id: order.replace(/^-/, ''), desc: order.startsWith('-') }] : []
}

function FlagLink({ id }: { id: number }): JSX.Element {
    return (
        <Button
            variant="link-muted"
            size="inline"
            nativeButton={false}
            aria-label="Open feature flag"
            render={<LinkPrimitive to={urls.featureFlag(id)} target="_blank" />}
        >
            <IconOpenInNew />
        </Button>
    )
}

export function QuillExperimentFlagKeyInput({
    flagKey,
    onFlagKeyChange,
    isExistingFlag,
    sourceExperiment,
    featureFlags,
    featureFlagsLoading,
    featureFlagFilters,
    onFeatureFlagFiltersChange,
    featureFlagPagination,
    onSelectExistingFlag,
    showReuseFlag,
    onToggleReuseFlag,
}: ExperimentFlagKeyInputProps): JSX.Element {
    const ongoing = isOngoingExperiment(sourceExperiment)
    const sourceFlag = sourceExperiment.feature_flag
    const pageSize = featureFlagPagination.pageSize ?? FLAGS_PER_PAGE
    const entryCount = featureFlagPagination.entryCount ?? 0
    const resetLink = (
        <Button
            variant="link"
            size="inline"
            nativeButton={false}
            render={<LinkPrimitive to={RESET_ANALYSIS_DOCS_URL} target="_blank" />}
        >
            Reset analysis
        </Button>
    )

    const columns: DataTableProps<FeatureFlagType, unknown>['columns'] = [
        {
            id: 'key',
            header: 'Key',
            cell: ({ row: { original } }) => (
                <span className="flex items-center gap-1">
                    <Text size="sm" weight="semibold">
                        {original.key}
                    </Text>
                    <FlagLink id={original.id as number} />
                </span>
            ),
        },
        {
            id: 'name',
            header: 'Name',
            meta: { expand: true },
            cell: ({ row: { original } }) => original.name,
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row: { original } }) =>
                original.key === sourceFlag?.key ? null : (
                    <Button
                        variant="outline"
                        size="xs"
                        disabledReason={flagSelectDisabledReason(original)}
                        onClick={() => onSelectExistingFlag(original.key ?? '')}
                    >
                        Select
                    </Button>
                ),
        },
    ]

    return (
        <>
            <Field>
                <FieldLabel htmlFor="experiment-flag-key">Feature flag key</FieldLabel>
                <Input
                    id="experiment-flag-key"
                    value={flagKey}
                    onChange={(event) => onFlagKeyChange(event.target.value)}
                    placeholder={FLAG_KEY_PLACEHOLDER}
                    data-attr="experiment-flag-key-input"
                />
                {flagKey && (
                    <FieldDescription>{flagKeyHint(flagKey, isExistingFlag, sourceExperiment)}</FieldDescription>
                )}
                {isExistingFlag && (
                    <Item variant="outline" size="sm" tone={ongoing ? 'warning' : 'info'}>
                        <ItemMedia variant="icon" aria-hidden>
                            {ongoing ? <IconWarning /> : <IconInfo />}
                        </ItemMedia>
                        <ItemContent className="min-w-0">
                            <ItemDescription className="line-clamp-none">
                                <ReuseFlagCopy ongoing={ongoing} resetLink={resetLink} />
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )}
            </Field>

            {!showReuseFlag ? (
                <div>
                    <Button variant="outline" size="sm" onClick={() => onToggleReuseFlag(true)}>
                        <IconCopy />
                        {REUSE_FLAG_LABEL}
                    </Button>
                </div>
            ) : (
                <>
                    <Field>
                        <FieldLabel>Use the same flag</FieldLabel>
                        <Item variant="outline" size="sm">
                            <ItemContent className="min-w-0">
                                <ItemTitle>
                                    <code className="text-xs">{sourceFlag?.key}</code>
                                    <FlagLink id={sourceFlag?.id as number} />
                                </ItemTitle>
                            </ItemContent>
                            <ItemActions>
                                <Button
                                    variant="outline"
                                    size="xs"
                                    onClick={() => onSelectExistingFlag(sourceFlag?.key ?? '')}
                                >
                                    Select
                                </Button>
                            </ItemActions>
                        </Item>
                    </Field>
                    <Field>
                        <FieldLabel>Choose an existing flag</FieldLabel>
                        <div className="flex flex-wrap items-center gap-2">
                            <Input
                                type="search"
                                className="flex-1"
                                placeholder="Search for feature flags"
                                maxLength={FEATURE_FLAG_SEARCH_MAX_LENGTH}
                                value={featureFlagFilters.search || ''}
                                onChange={(event) =>
                                    onFeatureFlagFiltersChange({ search: event.target.value, page: 1 })
                                }
                                data-attr="feature-flag-search"
                            />
                            <Select
                                value={featureFlagFilters.type ?? 'all'}
                                onValueChange={(next: string | null) =>
                                    next &&
                                    onFeatureFlagFiltersChange({
                                        type: next === 'all' ? undefined : (next as FeatureFlagsFilters['type']),
                                        page: 1,
                                    })
                                }
                            >
                                <SelectTrigger size="sm" data-attr="feature-flag-select-type">
                                    <SelectValue>
                                        {(current: string) =>
                                            `Type: ${FLAG_TYPE_OPTIONS.find((option) => option.value === current)?.label ?? current}`
                                        }
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    {FLAG_TYPE_OPTIONS.map((option) => (
                                        <SelectItem key={option.value} value={option.value}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <Card size="sm" flush className="pt-0">
                            <DataTable
                                columns={columns}
                                data={featureFlags.results}
                                fullWidth
                                size="sm"
                                getRowId={(flag) => String(flag.id)}
                                sorting={sortingFromOrder(featureFlagFilters.order)}
                                onSortingChange={([sort]) =>
                                    onFeatureFlagFiltersChange({
                                        order: sort ? `${sort.desc ? '-' : ''}${sort.id}` : undefined,
                                        page: 1,
                                    })
                                }
                                empty={
                                    featureFlagsLoading ? (
                                        <Skeleton className="h-6 w-full" />
                                    ) : (
                                        <Text size="xs" variant="muted">
                                            {NO_MATCHING_FLAGS}
                                        </Text>
                                    )
                                }
                            />
                            {entryCount > pageSize && (
                                <QuillTablePagination
                                    currentPage={featureFlagPagination.currentPage ?? 1}
                                    pageCount={Math.ceil(entryCount / pageSize)}
                                    pageSize={pageSize}
                                    total={entryCount}
                                    onPageChange={(page) => onFeatureFlagFiltersChange({ page })}
                                />
                            )}
                        </Card>
                    </Field>
                </>
            )}
        </>
    )
}
