import { type ReactNode, useId, useState } from 'react'

import { IconPencil, IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardContent,
    Checkbox,
    Field,
    FieldLabel,
    FieldTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { QuillTagsDialog } from 'products/experiments/frontend/components/QuillTagsDialog'
import { SummarizeExperimentButton } from 'products/experiments/frontend/components/SummarizeExperimentButton'

import {
    BASELINE_HELP,
    COMPLETED_WINDOWS_HELP,
    CUPED_DEFAULT_SETTINGS_URL,
    CUPED_HELP,
    HYPOTHESIS_PLACEHOLDER,
    HypothesisModals,
    useHypothesisPanel,
} from './hypothesisPanel'
import { QuillHelpTooltip, QuillSectionHeading } from './QuillCardParts'

function SettingRow({
    label,
    help,
    htmlFor,
    children,
    onEdit,
    editLabel,
    editDisabledReason,
}: {
    label: string
    help?: string
    htmlFor?: string
    children: ReactNode
    onEdit?: () => void
    editLabel?: string
    editDisabledReason?: string
}): JSX.Element {
    return (
        <Field orientation="horizontal" className="min-h-8 gap-x-6">
            <div className="flex w-36 shrink-0 items-center gap-1">
                {htmlFor ? (
                    <FieldLabel htmlFor={htmlFor} className="font-normal text-muted-foreground">
                        {label}
                    </FieldLabel>
                ) : (
                    <FieldTitle className="text-xs text-muted-foreground">{label}</FieldTitle>
                )}
                {help && <QuillHelpTooltip label={label} help={help} />}
            </div>
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
                {children}
                {onEdit && editLabel && (
                    <Button
                        size="icon-xs"
                        aria-label={editLabel}
                        tooltip={editLabel}
                        disabledReason={editDisabledReason}
                        onClick={onEdit}
                    >
                        <IconPencil />
                    </Button>
                )}
            </div>
        </Field>
    )
}

export function QuillHypothesis(): JSX.Element {
    const panel = useHypothesisPanel()
    const baselineId = useId()
    const [tagsOpen, setTagsOpen] = useState(false)
    const completedWindowsId = useId()
    const { isBayesian, cupedEnabled, lockedReason, tags } = panel

    return (
        <Card className="h-full">
            <CardContent className="flex h-full flex-col gap-4">
                <section className="flex min-h-0 flex-col gap-1">
                    <div className="flex items-center gap-1">
                        <QuillSectionHeading>Hypothesis</QuillSectionHeading>
                        <Button
                            size="icon-xs"
                            aria-label="Edit hypothesis"
                            tooltip="Edit hypothesis"
                            onClick={panel.openDescriptionModal}
                        >
                            <IconPencil />
                        </Button>
                    </div>
                    <div
                        className="max-h-40 overflow-y-auto scroll-mask-y-4 scroll-py-4"
                        data-attr="experiment-hypothesis-text"
                    >
                        {panel.description ? (
                            <Text size="xs" render={<p className="m-0 whitespace-pre-wrap" />}>
                                {panel.description}
                            </Text>
                        ) : (
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                {HYPOTHESIS_PLACEHOLDER}
                            </Text>
                        )}
                    </div>
                </section>

                <div className="mt-auto flex flex-col gap-4">
                    {panel.showResults && (
                        <>
                            <Separator />
                            <section className="flex flex-col items-start gap-2">
                                <QuillSectionHeading>Results</QuillSectionHeading>
                                <SummarizeExperimentButton />
                            </section>
                        </>
                    )}
                    <Separator />
                    <section className="flex flex-col gap-2">
                        <QuillSectionHeading>Settings</QuillSectionHeading>
                        <div className="flex flex-col">
                            <SettingRow
                                label="Statistics"
                                onEdit={panel.openStatsEngineModal}
                                editLabel="Edit statistics settings"
                                editDisabledReason={lockedReason}
                            >
                                <Text size="xs" render={<span />}>
                                    {isBayesian ? 'Bayesian' : 'Frequentist'} · {panel.confidenceDisplay}
                                    {!isBayesian && panel.sequentialEnabled && ' · Sequential testing'}
                                </Text>
                            </SettingRow>
                            <SettingRow
                                label="CUPED"
                                help={CUPED_HELP}
                                onEdit={panel.openCupedModal}
                                editLabel="Edit CUPED settings"
                                editDisabledReason={lockedReason}
                            >
                                <Badge variant={cupedEnabled ? 'success' : 'default'}>
                                    {cupedEnabled ? 'Enabled' : 'Disabled'}
                                </Badge>
                                {cupedEnabled && (
                                    <Text size="xs" render={<span />}>
                                        {panel.cupedLookbackDays}-day lookback
                                    </Text>
                                )}
                                {panel.cupedFromTeamDefault && (
                                    <Text size="xs" render={<span />}>
                                        <Button
                                            variant="link"
                                            size="inline"
                                            nativeButton={false}
                                            render={<LinkPrimitive to={CUPED_DEFAULT_SETTINGS_URL} />}
                                        >
                                            Project default
                                        </Button>
                                    </Text>
                                )}
                            </SettingRow>
                            <SettingRow label="Baseline variant" help={BASELINE_HELP} htmlFor={baselineId}>
                                <Select
                                    value={panel.baselineVariantKey}
                                    onValueChange={(value) => {
                                        if (typeof value === 'string') {
                                            panel.setBaselineVariant(value)
                                        }
                                    }}
                                    disabled={!!lockedReason || panel.saving}
                                >
                                    <SelectTrigger
                                        id={baselineId}
                                        render={<Button variant="outline" left disabledReason={lockedReason} />}
                                    >
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {panel.variantKeys.map((key) => (
                                            <SelectItem key={key} value={key}>
                                                {key}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </SettingRow>
                            <SettingRow
                                label="Completed windows"
                                help={COMPLETED_WINDOWS_HELP}
                                htmlFor={completedWindowsId}
                            >
                                <Field orientation="horizontal" className="w-auto">
                                    <Checkbox
                                        id={completedWindowsId}
                                        checked={panel.onlyCountMaturedUsers}
                                        disabledReason={lockedReason ?? (panel.saving ? 'Saving' : undefined)}
                                        onCheckedChange={(checked) => panel.setOnlyCountMaturedUsers(checked)}
                                    />
                                    <FieldLabel htmlFor={completedWindowsId} className="font-normal">
                                        Required
                                    </FieldLabel>
                                </Field>
                            </SettingRow>
                            <SettingRow label="Tags">
                                {tags.length > 0 ? (
                                    <span className="flex flex-wrap items-center gap-1">
                                        {tags.map((tag) => (
                                            <Badge key={tag}>{tag}</Badge>
                                        ))}
                                    </span>
                                ) : panel.canEditExperiment ? null : (
                                    <Text size="xs" variant="muted" render={<span />}>
                                        None
                                    </Text>
                                )}
                                {panel.canEditExperiment && (
                                    <Button
                                        size="icon-xs"
                                        aria-label={tags.length > 0 ? 'Manage tags' : 'Add tags'}
                                        tooltip={tags.length > 0 ? 'Manage tags' : 'Add tags'}
                                        onClick={() => setTagsOpen(true)}
                                        data-attr="experiment-tags"
                                    >
                                        {tags.length > 0 ? <IconPencil /> : <IconPlus />}
                                    </Button>
                                )}
                            </SettingRow>
                        </div>
                    </section>
                </div>
            </CardContent>

            <HypothesisModals />
            <QuillTagsDialog
                open={tagsOpen}
                name={panel.name}
                tags={tags}
                onClose={() => setTagsOpen(false)}
                onSave={(next) => {
                    panel.setTags(next)
                    setTagsOpen(false)
                }}
            />
        </Card>
    )
}
