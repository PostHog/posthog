import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconMegaphone, IconPlus, IconSearch } from '@posthog/icons'
import {
    Button,
    DataTable,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { HogFunctionTemplateType } from '~/types'

import { SourceReleaseTag } from 'products/data_warehouse/frontend/shared/components/SourceReleaseTag'

import { HogFunctionIcon } from '../configuration/HogFunctionIcon'
import { HogFunctionStatusTag } from '../misc/HogFunctionStatusTag'
import { DELIVERY_TYPE_FILTER_OPTIONS } from './DeliveryTypeTag'
import { hogFunctionRequestModalLogic } from './hogFunctionRequestModalLogic'
import { getTemplateAccessDisabledReason } from './HogFunctionTemplateList'
import { HogFunctionTemplateListLogicProps, hogFunctionTemplateListLogic } from './hogFunctionTemplateListLogic'
import { QuillDeliveryTypeTag } from './QuillDeliveryTypeTag'

export type QuillHogFunctionTemplateListProps = HogFunctionTemplateListLogicProps & {
    extraControls?: JSX.Element
    hideFeedback: boolean
}

export function QuillHogFunctionTemplateList({
    extraControls,
    hideFeedback,
    ...props
}: QuillHogFunctionTemplateListProps): JSX.Element {
    const { loading, filteredTemplates, filters, templates, urlForTemplate, hasMultipleDeliveryTypes } = useValues(
        hogFunctionTemplateListLogic(props)
    )
    const { setFilters, resetFilters, registerInterest } = useActions(hogFunctionTemplateListLogic(props))
    const { openFeedbackDialog } = useActions(hogFunctionRequestModalLogic)

    const columns = useMemo<ColumnDef<HogFunctionTemplateType>[]>(
        () => [
            {
                id: 'icon',
                header: '',
                enableSorting: false,
                cell: ({ row }) => (
                    <HogFunctionIcon
                        src={row.original.icon_url}
                        className={row.original.icon_class_name}
                        size="small"
                    />
                ),
            },
            {
                id: 'name',
                header: 'Name',
                accessorFn: (template) => template.name || '',
                meta: { expand: true },
                cell: ({ row }) => {
                    const template = row.original
                    const url = getTemplateAccessDisabledReason(template) ? null : urlForTemplate(template)

                    return (
                        <div className="flex flex-col gap-1 py-1">
                            <div className="flex flex-wrap items-center gap-1">
                                {url ? (
                                    <Button
                                        variant="link-foreground"
                                        size="sm"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={url} />}
                                    >
                                        {template.name}
                                    </Button>
                                ) : (
                                    <Text size="xs" weight="semibold" render={<span />}>
                                        {template.name}
                                    </Text>
                                )}
                                {template.status && <HogFunctionStatusTag status={template.status} />}
                                {template.releaseStatus && <SourceReleaseTag releaseStatus={template.releaseStatus} />}
                            </div>
                            {template.description ? (
                                <Text size="xs" variant="muted" render={<div />}>
                                    {typeof template.description === 'string' ? (
                                        <LemonMarkdown lowKeyHeadings disableImages>
                                            {template.description}
                                        </LemonMarkdown>
                                    ) : (
                                        template.description
                                    )}
                                </Text>
                            ) : null}
                        </div>
                    )
                },
            },
            ...(hasMultipleDeliveryTypes
                ? [
                      {
                          id: 'delivery_type',
                          header: 'Type',
                          enableSorting: false,
                          cell: ({ row }) => <QuillDeliveryTypeTag item={row.original} />,
                      } satisfies ColumnDef<HogFunctionTemplateType>,
                  ]
                : []),
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) => {
                    const template = row.original

                    if (template.status === 'coming_soon') {
                        return (
                            <Button
                                variant="primary"
                                data-attr="request-destination"
                                className="whitespace-nowrap"
                                onClick={() => registerInterest(template)}
                            >
                                <IconMegaphone />
                                Notify me
                            </Button>
                        )
                    }

                    const url = urlForTemplate(template)

                    return (
                        <Button
                            variant="primary"
                            data-attr="new-destination"
                            className="whitespace-nowrap"
                            disabledReason={getTemplateAccessDisabledReason(template)}
                            nativeButton={!url}
                            render={url ? <LinkPrimitive to={url} /> : undefined}
                        >
                            <IconPlus />
                            Create
                        </Button>
                    )
                },
            },
        ],
        [hasMultipleDeliveryTypes, urlForTemplate, registerInterest]
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <InputGroup size="sm" className="grow min-w-48 max-w-80">
                    <InputGroupAddon align="inline-start">
                        <IconSearch />
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        placeholder="Search..."
                        aria-label="Search"
                        value={filters.search ?? ''}
                        onChange={(event) => setFilters({ search: event.target.value })}
                    />
                </InputGroup>
                {!hideFeedback ? (
                    <Button variant="link-muted" onClick={() => openFeedbackDialog(props.type)}>
                        Can't find what you're looking for?
                    </Button>
                ) : null}
                <div className="flex flex-wrap items-center gap-2 ml-auto">
                    {hasMultipleDeliveryTypes && (
                        <Select
                            items={DELIVERY_TYPE_FILTER_OPTIONS}
                            value={filters.deliveryType ?? null}
                            onValueChange={(value) => setFilters({ deliveryType: value ?? undefined })}
                        >
                            <SelectTrigger aria-label="Delivery type" className="w-fit">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {DELIVERY_TYPE_FILTER_OPTIONS.map((option) => (
                                    <SelectItem key={option.value ?? 'all'} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    )}
                    {extraControls}
                </div>
            </div>

            {loading && filteredTemplates.length === 0 ? (
                <Skeleton className="h-40" />
            ) : (
                <div aria-busy={loading}>
                    <DataTable
                        columns={columns}
                        data={filteredTemplates}
                        fullWidth
                        empty={
                            <Empty>
                                <EmptyHeader>
                                    <EmptyDescription>
                                        {templates.length === 0
                                            ? 'No results found'
                                            : 'Nothing found matching filters.'}
                                    </EmptyDescription>
                                </EmptyHeader>
                                {templates.length > 0 ? (
                                    <EmptyContent>
                                        <Button variant="outline" onClick={() => resetFilters()}>
                                            Clear filters
                                        </Button>
                                    </EmptyContent>
                                ) : null}
                            </Empty>
                        }
                    />
                </div>
            )}
        </div>
    )
}
