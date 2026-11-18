import {
    Badge,
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldContent,
    FieldDescription,
    FieldGroup,
    FieldLabel,
    FieldLegend,
    FieldSet,
    Label,
    RadioGroup,
    RadioGroupItem,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { QuillTestAccountFilterSwitch } from 'lib/components/QuillTestAccountFilterSwitch'

import { resolveFilterTestAccounts } from '../exposureContract'
import {
    EXPOSURE_CRITERIA_INTRO,
    EXPOSURE_MODE_TITLES,
    ExposureCriteriaEditors,
    type ExposureCriteriaModalModel,
    type ExposureMode,
    MULTIPLE_VARIANT_HANDLING_OPTIONS,
    exposureModeDescription,
    multipleVariantHandlingHelp,
} from './exposureCriteriaModel'

export function QuillExposureCriteriaModal({ model }: { model: ExposureCriteriaModalModel }): JSX.Element {
    const {
        isOpen,
        close,
        save,
        saveDisabledReason,
        exposureCriteria,
        setExposureCriteria,
        resolvedExposureEvent,
        hasFilters,
        warehouseExposure,
        mode,
        selectMode,
        modes,
    } = model
    const handling = exposureCriteria?.multiple_variant_handling || 'exclude'
    const eventTag = <Badge>{resolvedExposureEvent}</Badge>

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && close()}>
            <DialogContent size="wide" data-attr="experiment-exposure-criteria-modal">
                <DialogHeader>
                    <DialogTitle>Edit exposure criteria</DialogTitle>
                    <DialogDescription>{EXPOSURE_CRITERIA_INTRO}</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <FieldSet>
                            <FieldLegend variant="label">Exposure</FieldLegend>
                            <RadioGroup value={mode} onValueChange={(next) => selectMode(next as ExposureMode)}>
                                {modes.map(({ mode: option, blockedReason }) => (
                                    <Field key={option} orientation="horizontal" className="items-start">
                                        <RadioGroupItem
                                            value={option}
                                            id={`exposure-mode-${option}`}
                                            disabled={!!blockedReason}
                                            data-attr={
                                                option === 'warehouse-native'
                                                    ? 'experiment-exposure-warehouse-native'
                                                    : `experiment-exposure-${option}`
                                            }
                                        />
                                        <FieldContent>
                                            <Label htmlFor={`exposure-mode-${option}`}>
                                                {EXPOSURE_MODE_TITLES[option]}
                                            </Label>
                                            <FieldDescription>
                                                {exposureModeDescription(option, eventTag)}
                                            </FieldDescription>
                                            {blockedReason && <FieldDescription>{blockedReason}</FieldDescription>}
                                        </FieldContent>
                                    </Field>
                                ))}
                            </RadioGroup>
                        </FieldSet>
                        <ExposureCriteriaEditors model={model} />
                        <Field className="max-w-md">
                            <FieldLabel>Multiple variant handling</FieldLabel>
                            <Select
                                value={handling}
                                onValueChange={(value) =>
                                    value &&
                                    setExposureCriteria({
                                        ...exposureCriteria,
                                        multiple_variant_handling: value as 'exclude' | 'first_seen',
                                    })
                                }
                            >
                                <SelectTrigger>
                                    <SelectValue>
                                        {(value: string) =>
                                            MULTIPLE_VARIANT_HANDLING_OPTIONS.find((option) => option.value === value)
                                                ?.label ?? value
                                        }
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    {MULTIPLE_VARIANT_HANDLING_OPTIONS.map((option) => (
                                        <SelectItem key={option.value} value={option.value} data-attr={option.dataAttr}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <FieldDescription>{multipleVariantHandlingHelp(handling)}</FieldDescription>
                        </Field>
                        {/* Test account filters read PostHog person and event properties, which warehouse rows do not have */}
                        {!warehouseExposure && (
                            <QuillTestAccountFilterSwitch
                                checked={hasFilters && resolveFilterTestAccounts(exposureCriteria)}
                                onChange={(checked: boolean) =>
                                    setExposureCriteria({ ...exposureCriteria, filterTestAccounts: checked })
                                }
                            />
                        )}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={close}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={save} disabledReason={saveDisabledReason ?? undefined}>
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
