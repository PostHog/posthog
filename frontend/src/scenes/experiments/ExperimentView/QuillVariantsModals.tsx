import { IconInfo } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldDescription,
    FieldLabel,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { VariantDistributionEditor } from '~/scenes/experiments/ExperimentForm/VariantDistributionEditor'

import { DISTRIBUTION_CHANGE_WARNING, DISTRIBUTION_DOCS_URL, useDistributionModal } from './DistributionTable'
import { HOLDOUT_HELP, useHoldoutSelector } from './HoldoutSelector'
import { QuillHelpTooltip } from './QuillCardParts'
import {
    RELEASE_CONDITIONS_WARNING,
    ReleaseConditionsEditor,
    useReleaseConditionsModal,
} from './ReleaseConditionsTable'

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

export function QuillReleaseConditionsModal(): JSX.Element {
    const model = useReleaseConditionsModal()

    return (
        <Dialog open={model.isOpen} onOpenChange={(open: boolean) => !open && model.close()}>
            <DialogContent size="wide" className="max-w-2xl" data-attr="experiment-release-conditions-modal">
                <DialogHeader>
                    <DialogTitle>Change release conditions</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <InfoItem>{RELEASE_CONDITIONS_WARNING}</InfoItem>
                        {model.isOpen && <ReleaseConditionsEditor {...model} />}
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={model.close}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={() => void model.save()}>
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

function QuillHoldoutSelector(): JSX.Element {
    const { options, value, lockedReason, onChange } = useHoldoutSelector()
    const current = value === null ? 'none' : String(value)

    return (
        <Field>
            <span className="flex items-center gap-1">
                <FieldLabel>Holdout group</FieldLabel>
                <QuillHelpTooltip label="Holdout group" help={HOLDOUT_HELP} />
            </span>
            <Select
                value={current}
                disabled={!!lockedReason}
                onValueChange={(next) => next && onChange(next === 'none' ? null : Number(next))}
            >
                <SelectTrigger className="w-64" data-attr="experiment-holdout-selector">
                    <SelectValue>
                        {(selected: string) =>
                            options.find(
                                (option) => (option.value === null ? 'none' : String(option.value)) === selected
                            )?.label ?? selected
                        }
                    </SelectValue>
                </SelectTrigger>
                <SelectContent>
                    {options.map((option) => (
                        <SelectItem
                            key={option.value ?? 'none'}
                            value={option.value === null ? 'none' : String(option.value)}
                        >
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            {lockedReason && <FieldDescription>{lockedReason}</FieldDescription>}
        </Field>
    )
}

export function QuillDistributionModal(): JSX.Element {
    const {
        isOpen,
        close,
        save,
        loading,
        saveDisabledReason,
        variants,
        setVariants,
        rolloutPercentage,
        setRolloutPercentage,
    } = useDistributionModal()

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && close()}>
            <DialogContent size="wide" className="max-w-2xl" data-attr="experiment-distribution-modal">
                <DialogHeader>
                    <DialogTitle>Change experiment distribution</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <InfoItem>
                            {DISTRIBUTION_CHANGE_WARNING}{' '}
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to={DISTRIBUTION_DOCS_URL} target="_blank" />}
                            >
                                Read more
                            </Button>
                        </InfoItem>
                        <VariantDistributionEditor
                            variants={variants}
                            onVariantsChange={setVariants}
                            rolloutPercentage={rolloutPercentage}
                            onRolloutPercentageChange={setRolloutPercentage}
                        />
                        <QuillHoldoutSelector />
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={close}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={save} loading={loading} disabledReason={saveDisabledReason}>
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
