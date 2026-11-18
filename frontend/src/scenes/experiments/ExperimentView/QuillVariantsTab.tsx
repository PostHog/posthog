import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFlag, IconInfo, IconLock, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    DataTable,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Switch,
    Text,
    Textarea,
} from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { AuthorizedUrlList } from '~/lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from '~/lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IconOpenInApp } from '~/lib/lemon-ui/icons'
import { FeatureFlagGroupType, MultivariateFlagVariant } from '~/types'

import { experimentLogic } from '../experimentLogic'
import {
    DISTRIBUTION_EXCLUDE_HELP,
    DISTRIBUTION_LAST_VARIANT_REASON,
    DISTRIBUTION_LAST_VARIANT_WARNING,
    PREVIEW_DOMAIN_DESCRIPTION,
    PREVIEW_DOMAIN_TITLE,
    holdoutNote,
    previewQuery,
    useDistributionTable,
} from './DistributionTable'
import { QuillHelpTooltip, QuillSectionHeading } from './QuillCardParts'
import { QuillVariantTag } from './QuillVariantTag'
import { useReleaseConditionsTable } from './ReleaseConditionsTable'
import { VariantScreenshot } from './VariantScreenshot'

function SectionHeader({
    title,
    action,
    onAction,
}: {
    title: string
    action: string
    onAction: () => void
}): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-2">
            <QuillSectionHeading>{title}</QuillSectionHeading>
            <Button variant="outline" onClick={onAction}>
                <IconFlag />
                {action}
            </Button>
        </div>
    )
}

function NoteItem({ tone, children }: { tone: 'info' | 'warning'; children: React.ReactNode }): JSX.Element {
    return (
        <Item variant="outline" size="sm" tone={tone}>
            <ItemMedia variant="icon" aria-hidden>
                {tone === 'info' ? <IconInfo /> : <IconWarning />}
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemDescription className="line-clamp-none">{children}</ItemDescription>
            </ItemContent>
        </Item>
    )
}

function QuillReleaseConditionsTable(): JSX.Element {
    const { groups, releaseText, openReleaseConditions } = useReleaseConditionsTable()

    const columns: DataTableProps<FeatureFlagGroupType, unknown>['columns'] = [
        {
            id: 'set',
            header: 'Set',
            enableSorting: false,
            cell: ({ row }) => (
                <Text
                    size="xs"
                    weight="semibold"
                    render={<span className="whitespace-nowrap" />}
                >{`Set ${row.index + 1}`}</Text>
            ),
        },
        {
            id: 'rollout',
            header: 'Rollout',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row: { original } }) => {
                const text = releaseText(original)
                return text.startsWith('100% of') ? <Badge variant="info">{text}</Badge> : text
            },
        },
        {
            id: 'override',
            header: 'Override',
            enableSorting: false,
            cell: ({ row: { original } }) => original.variant || '--',
        },
    ]

    return (
        <section className="flex flex-col gap-2" data-attr="experiment-release-conditions">
            <SectionHeader
                title="Release conditions"
                action="Manage release conditions"
                onAction={openReleaseConditions}
            />
            <Card size="sm" flush className="pt-0">
                <DataTable columns={columns} data={groups} fullWidth size="sm" />
            </Card>
        </section>
    )
}

function QuillVariantNotes({ variantKey }: { variantKey: string }): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperimentVariantNotes } = useActions(experimentLogic)
    const note = experiment.parameters?.variant_notes?.[variantKey] ?? ''
    const [draft, setDraft] = useState<string | null>(null)

    return (
        <Textarea
            aria-label={`Notes for ${variantKey}`}
            className="h-20 min-w-40 resize-none"
            value={draft ?? note}
            onFocus={() => setDraft(note)}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={() => {
                if (draft !== null && draft !== note) {
                    updateExperimentVariantNotes({ ...experiment.parameters?.variant_notes, [variantKey]: draft })
                }
                setDraft(null)
            }}
            data-attr="experiment-variant-notes"
        />
    )
}

function PreviewDialog({
    experimentId,
    variant,
    onClose,
}: {
    experimentId: number | string | undefined
    variant: string | null
    onClose: () => void
}): JSX.Element {
    return (
        <Dialog open={!!variant} onOpenChange={(open: boolean) => !open && onClose()}>
            <DialogContent size="wide" className="max-w-2xl" data-attr="experiment-preview-variant-modal">
                <DialogHeader>
                    <DialogTitle>{PREVIEW_DOMAIN_TITLE}</DialogTitle>
                    <DialogDescription>{PREVIEW_DOMAIN_DESCRIPTION}</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    {variant && (
                        <AuthorizedUrlList
                            query={previewQuery(experimentId, variant)}
                            experimentId={typeof experimentId === 'number' ? experimentId : undefined}
                            type={AuthorizedUrlListType.WEB_EXPERIMENTS}
                        />
                    )}
                </DialogBody>
                <DialogFooter showCloseButton />
            </DialogContent>
        </Dialog>
    )
}

function QuillDistributionTable(): JSX.Element {
    const {
        experiment,
        baselineKey,
        excludedVariants,
        excludedVariantsEnabled,
        hasOnlyOneTestVariant,
        holdoutKey,
        tableData,
        experimentUpdateLoading,
        setVariantExcluded,
        openDistribution,
    } = useDistributionTable()
    const [previewVariant, setPreviewVariant] = useState<string | null>(null)

    const columns: DataTableProps<MultivariateFlagVariant, unknown>['columns'] = [
        {
            id: 'variant',
            header: 'Variant',
            enableSorting: false,
            cell: ({ row: { original } }) => <QuillVariantTag variantKey={original.key} />,
        },
        {
            id: 'split',
            header: 'Split',
            enableSorting: false,
            cell: ({ row: { original } }) => `${original.rollout_percentage}%`,
        },
        ...(excludedVariantsEnabled
            ? [
                  {
                      id: 'analysis',
                      header: () => (
                          <span className="inline-flex items-center gap-1">
                              Include in analysis
                              <QuillHelpTooltip label="Include in analysis" help={DISTRIBUTION_EXCLUDE_HELP} />
                          </span>
                      ),
                      enableSorting: false,
                      cell: ({ row: { original } }: { row: { original: MultivariateFlagVariant } }) => {
                          if (original.key === holdoutKey) {
                              return <Text variant="muted">-</Text>
                          }
                          if (original.key === baselineKey) {
                              return (
                                  <Badge>
                                      <IconLock />
                                      Baseline
                                  </Badge>
                              )
                          }
                          const excluded = excludedVariants.includes(original.key)
                          // Re-including stays possible; excluding the last test variant does not.
                          const disableToggle = !excluded && hasOnlyOneTestVariant
                          return (
                              <span className="flex items-center gap-2">
                                  <Switch
                                      aria-label={`Include ${original.key} in analysis`}
                                      checked={!excluded}
                                      onCheckedChange={(checked) => setVariantExcluded(original.key, !checked)}
                                      disabled={experimentUpdateLoading}
                                      disabledReason={disableToggle ? DISTRIBUTION_LAST_VARIANT_REASON : undefined}
                                  />
                                  {excluded && <Badge variant="warning">Excluded</Badge>}
                              </span>
                          )
                      },
                  },
              ]
            : []),
        {
            id: 'screenshot',
            header: 'Screenshot',
            enableSorting: false,
            cell: ({ row: { original } }) =>
                original.key === holdoutKey ? (
                    <div className="h-16" />
                ) : (
                    <div className="my-2">
                        <VariantScreenshot variantKey={original.key} rolloutPercentage={original.rollout_percentage} />
                    </div>
                ),
        },
        {
            id: 'notes',
            header: 'Notes',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row: { original } }) =>
                original.key === holdoutKey ? (
                    <div className="h-16" />
                ) : (
                    <QuillVariantNotes variantKey={original.key} />
                ),
        },
        ...(experiment.type === 'web'
            ? [
                  {
                      id: 'preview',
                      header: 'Preview',
                      enableSorting: false,
                      cell: ({ row: { original } }: { row: { original: MultivariateFlagVariant } }) => (
                          <Button variant="outline" onClick={() => setPreviewVariant(original.key)}>
                              Preview variant
                              <IconOpenInApp />
                          </Button>
                      ),
                  },
              ]
            : []),
    ]

    return (
        <section className="flex flex-col gap-2" data-attr="experiment-distribution">
            <SectionHeader title="Distribution" action="Manage distribution" onAction={openDistribution} />
            {experiment.holdout && (
                <NoteItem tone="info">{holdoutNote(experiment.holdout.filters[0].rollout_percentage)}</NoteItem>
            )}
            {excludedVariants.length > 0 && hasOnlyOneTestVariant && (
                <NoteItem tone="warning">{DISTRIBUTION_LAST_VARIANT_WARNING}</NoteItem>
            )}
            <Card size="sm" flush className="pt-0">
                <DataTable
                    columns={columns}
                    data={tableData}
                    fullWidth
                    size="sm"
                    getRowId={(row) => row.key}
                    rowClassName={(row) =>
                        row.key === holdoutKey || excludedVariants.includes(row.key) ? 'bg-muted' : undefined
                    }
                />
            </Card>
            <PreviewDialog
                experimentId={experiment.id}
                variant={previewVariant}
                onClose={() => setPreviewVariant(null)}
            />
        </section>
    )
}

export function QuillVariantsTab(): JSX.Element {
    return (
        <div className="mt-2 flex flex-col gap-8" data-attr="experiment-variants-tab">
            <QuillReleaseConditionsTable />
            <QuillDistributionTable />
        </div>
    )
}
