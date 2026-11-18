import { IconGlobe, IconInfo, IconList, IconX } from '@posthog/icons'
import {
    Button,
    Checkbox,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Dot,
    Field,
    FieldContent,
    FieldDescription,
    FieldGroup,
    FieldLabel,
    FieldLegend,
    FieldSet,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Label,
    RadioGroup,
    RadioGroupItem,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
    Textarea,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ExperimentConclusion } from '~/types'

import { EXPERIMENT_CONCLUSION_DOT } from 'products/experiments/frontend/components/QuillStatusBadge'
import { CONCLUSION_DISPLAY_CONFIG } from 'products/experiments/frontend/constants'
import { hasFrozenExposureStamps } from 'products/experiments/frontend/experimentActions'

import { getExperimentVariants } from '../utils'
import {
    CONCLUSION_COMMENT_PLACEHOLDER,
    FROZEN_EXPOSURE_NOTE,
    FinishExperimentModalModel,
    PauseExperimentCopy,
    ResumeExperimentCopy,
    VARIANT_TO_KEEP_HELP,
    releaseOptions,
    useConclusionForm,
} from './experimentModalsModel'
import { QuillVariantTag } from './QuillVariantTag'

function InfoItem({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <Item variant="outline" size="sm" tone="info">
            <ItemMedia variant="icon" aria-hidden>
                <IconInfo />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemDescription className="line-clamp-none">{children}</ItemDescription>
            </ItemContent>
        </Item>
    )
}

function QuillConclusionForm(): JSX.Element {
    const { conclusion, comment, setConclusion, setComment } = useConclusionForm()

    return (
        <>
            <Field>
                <FieldLabel>Conclusion</FieldLabel>
                <Select
                    value={conclusion ?? null}
                    onValueChange={(value) => setConclusion((value as ExperimentConclusion) || undefined)}
                >
                    <SelectTrigger data-attr="experiment-conclusion-select">
                        <SelectValue placeholder="Select a conclusion">
                            {(value: ExperimentConclusion | null) =>
                                value ? (
                                    <span className="flex items-center gap-2">
                                        <Dot variant={EXPERIMENT_CONCLUSION_DOT[value] ?? 'default'} />
                                        {CONCLUSION_DISPLAY_CONFIG[value].title}
                                    </span>
                                ) : (
                                    'Select a conclusion'
                                )
                            }
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        {Object.values(ExperimentConclusion).map((value) => (
                            <SelectItem key={value} value={value}>
                                <span className="flex flex-col gap-0.5 py-1">
                                    <span className="flex items-center gap-2 font-semibold">
                                        <Dot variant={EXPERIMENT_CONCLUSION_DOT[value] ?? 'default'} />
                                        {CONCLUSION_DISPLAY_CONFIG[value].title}
                                    </span>
                                    <Text size="xs" variant="muted" render={<span />}>
                                        {CONCLUSION_DISPLAY_CONFIG[value].description}
                                    </Text>
                                </span>
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </Field>
            <Field>
                <FieldLabel htmlFor="experiment-conclusion-comment">Comment (optional)</FieldLabel>
                <Textarea
                    id="experiment-conclusion-comment"
                    rows={6}
                    maxLength={4000}
                    placeholder={CONCLUSION_COMMENT_PLACEHOLDER}
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                />
            </Field>
        </>
    )
}

export function QuillEditConclusionModal({
    isOpen,
    close,
    cancel,
    save,
    saveDisabledReason,
}: {
    isOpen: boolean
    close: () => void
    cancel: () => void
    save: () => void
    saveDisabledReason?: string
}): JSX.Element {
    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && close()}>
            <DialogContent data-attr="experiment-edit-conclusion-modal">
                <DialogHeader>
                    <DialogTitle>Edit conclusion</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>{isOpen && <QuillConclusionForm />}</FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={cancel}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={save} disabledReason={saveDisabledReason}>
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

export function QuillPauseResumeModal({
    kind,
    isOpen,
    close,
    confirm,
    confirmDisabledReason,
}: {
    kind: 'pause' | 'resume'
    isOpen: boolean
    close: () => void
    confirm: () => void
    confirmDisabledReason?: string
}): JSX.Element {
    const title = kind === 'pause' ? 'Pause experiment' : 'Resume experiment'
    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && close()}>
            <DialogContent data-attr={`experiment-${kind}-modal`}>
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <Text size="xs" render={<div className="flex flex-col gap-3" />}>
                        {kind === 'pause' ? <PauseExperimentCopy /> : <ResumeExperimentCopy />}
                    </Text>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={close}>
                        Cancel
                    </Button>
                    <Button
                        variant={kind === 'pause' ? 'destructive' : 'primary'}
                        onClick={confirm}
                        disabledReason={confirmDisabledReason}
                    >
                        {title}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

export function QuillFinishExperimentModal({ model }: { model: FinishExperimentModalModel }): JSX.Element {
    const {
        experiment,
        isOpen,
        isSingleVariantShipped,
        shippedVariantKey,
        endExperimentLoading,
        aggregationTargetName,
        selectedVariantKey,
        setSelectedVariantKey,
        releaseToEveryone,
        setReleaseToEveryone,
        openCleanupPr,
        setOpenCleanupPr,
        cleanupRepository,
        setCleanupRepository,
        setAsTeamDefault,
        setSetAsTeamDefault,
        cleanupTarget,
        cleanupPrAvailable,
        cleanupNeedsRepositoryPick,
        teamDefaultRestrictionReason,
        handleClose,
        handleEndExperiment,
        endDisabledReason,
    } = model
    const variants = getExperimentVariants(experiment)

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && handleClose()}>
            <DialogContent data-attr="experiment-end-modal">
                <DialogHeader>
                    <DialogTitle>End experiment</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        {isSingleVariantShipped ? (
                            <InfoItem>
                                <span className="inline-flex align-middle">
                                    <QuillVariantTag variantKey={shippedVariantKey || ''} />
                                </span>{' '}
                                is already rolled out to 100% of {aggregationTargetName}. Ending this experiment will
                                mark it as complete without changing the feature flag.
                            </InfoItem>
                        ) : (
                            <>
                                {hasFrozenExposureStamps(experiment) && <InfoItem>{FROZEN_EXPOSURE_NOTE}</InfoItem>}
                                <Field>
                                    <FieldLabel>Variant to keep (optional)</FieldLabel>
                                    <FieldDescription>{VARIANT_TO_KEEP_HELP}</FieldDescription>
                                    <span className="flex items-center gap-1">
                                        <Select
                                            value={selectedVariantKey ?? null}
                                            onValueChange={(value) => setSelectedVariantKey(value as string | null)}
                                        >
                                            <SelectTrigger className="w-1/2" data-attr="metrics-selector">
                                                <SelectValue placeholder="Select a variant">
                                                    {(value: string | null) =>
                                                        value ? (
                                                            <QuillVariantTag variantKey={value} />
                                                        ) : (
                                                            'Select a variant'
                                                        )
                                                    }
                                                </SelectValue>
                                            </SelectTrigger>
                                            <SelectContent>
                                                {variants.map(({ key }) => (
                                                    <SelectItem key={key} value={key}>
                                                        <QuillVariantTag variantKey={key} />
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                        {selectedVariantKey && (
                                            <Button
                                                size="icon-sm"
                                                aria-label="Clear variant"
                                                tooltip="Clear variant"
                                                onClick={() => setSelectedVariantKey(null)}
                                            >
                                                <IconX />
                                            </Button>
                                        )}
                                    </span>
                                </Field>
                                {selectedVariantKey && (
                                    <FieldSet>
                                        <FieldLegend variant="label">How to release this variant</FieldLegend>
                                        <RadioGroup
                                            value={releaseToEveryone ? 'everyone' : 'population'}
                                            onValueChange={(value) => setReleaseToEveryone(value === 'everyone')}
                                            data-attr="ship-variant-release-mode"
                                        >
                                            {releaseOptions(aggregationTargetName).map((option) => {
                                                const key = option.value ? 'everyone' : 'population'
                                                return (
                                                    <Field key={key} orientation="horizontal" className="items-start">
                                                        <RadioGroupItem
                                                            value={key}
                                                            id={`ship-variant-release-mode-${key}`}
                                                            data-attr={`ship-variant-release-mode-${key}`}
                                                        />
                                                        <FieldContent>
                                                            <Label
                                                                htmlFor={`ship-variant-release-mode-${key}`}
                                                                className="flex items-center gap-1.5"
                                                            >
                                                                {option.value ? <IconGlobe /> : <IconList />}
                                                                {option.label}
                                                                {option.recommended && (
                                                                    <span className="font-normal text-muted-foreground">
                                                                        (recommended)
                                                                    </span>
                                                                )}
                                                            </Label>
                                                            <FieldDescription>{option.description}</FieldDescription>
                                                        </FieldContent>
                                                    </Field>
                                                )
                                            })}
                                        </RadioGroup>
                                    </FieldSet>
                                )}
                            </>
                        )}
                        {isOpen && <QuillConclusionForm />}
                        {cleanupPrAvailable && (
                            <FieldSet>
                                <Field orientation="horizontal">
                                    <Checkbox
                                        id="experiment-open-cleanup-pr"
                                        checked={openCleanupPr}
                                        onCheckedChange={(checked) => setOpenCleanupPr(!!checked)}
                                        data-attr="experiment-open-cleanup-pr"
                                        disabledReason={
                                            cleanupTarget?.source === 'no_integration'
                                                ? 'Connect GitHub in your project settings to open cleanup PRs'
                                                : undefined
                                        }
                                    />
                                    <Label htmlFor="experiment-open-cleanup-pr">
                                        Open a draft PR removing <code>{experiment.feature_flag?.key}</code> from your
                                        code
                                    </Label>
                                </Field>
                                {openCleanupPr && cleanupTarget?.repository && (
                                    <FieldDescription>
                                        The PR will be opened in <code>{cleanupTarget.repository}</code>.
                                    </FieldDescription>
                                )}
                                {openCleanupPr && cleanupNeedsRepositoryPick && (
                                    <>
                                        <Field>
                                            <Select
                                                value={cleanupRepository}
                                                onValueChange={(value) => setCleanupRepository(value as string | null)}
                                            >
                                                <SelectTrigger data-attr="experiment-cleanup-repository">
                                                    <SelectValue placeholder="Select a repository" />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    {(cleanupTarget?.candidates ?? []).map((repository) => (
                                                        <SelectItem key={repository} value={repository}>
                                                            {repository}
                                                        </SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </Field>
                                        {!teamDefaultRestrictionReason && (
                                            <Field orientation="horizontal">
                                                <Checkbox
                                                    id="experiment-cleanup-repository-team-default"
                                                    checked={setAsTeamDefault}
                                                    onCheckedChange={(checked) => setSetAsTeamDefault(!!checked)}
                                                    data-attr="experiment-cleanup-repository-team-default"
                                                />
                                                <Label htmlFor="experiment-cleanup-repository-team-default">
                                                    Use this repository for all experiments in this project
                                                </Label>
                                            </Field>
                                        )}
                                    </>
                                )}
                            </FieldSet>
                        )}
                        {!isSingleVariantShipped && (
                            <InfoItem>
                                For more precise control over your release, adjust the rollout percentage and release
                                conditions in the{' '}
                                {experiment.feature_flag ? (
                                    <Button
                                        variant="link"
                                        size="inline"
                                        nativeButton={false}
                                        render={
                                            <LinkPrimitive
                                                to={urls.featureFlag(experiment.feature_flag.id)}
                                                target="_blank"
                                            />
                                        }
                                    >
                                        {experiment.feature_flag.key}
                                    </Button>
                                ) : null}{' '}
                                feature flag.
                            </InfoItem>
                        )}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={handleClose}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={handleEndExperiment}
                        loading={endExperimentLoading}
                        disabledReason={endDisabledReason}
                    >
                        End experiment
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
