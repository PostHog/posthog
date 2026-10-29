import { useActions, useValues } from 'kea'
import { type RefObject, useRef } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldDescription,
    FieldLabel,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Text,
} from '@posthog/quill'

import type { BetsDetailApi } from '../generated/api.schemas'
import { type PlanField, stepValue } from '../lib/plan'
import { betLogic } from '../logics/betLogic'

const FIELDS: { name: PlanField; label: string; unit: string; help: string; placeholder?: string }[] = [
    {
        name: 'audience',
        label: 'People a day',
        unit: 'people',
        help: 'People who reach the place this change touches.',
        placeholder: 'How many people a day',
    },
    {
        name: 'mde',
        label: 'Smallest change to find',
        unit: '%',
        help: 'A smaller change needs more days.',
    },
    { name: 'days', label: 'Days to run', unit: 'days', help: 'At least 2 days.' },
]

const MISSING_AUDIENCE = 'Not known yet. Count the people a day who reach the place this change touches.'

function PlanFieldRow({
    field,
    value,
    missing,
    disabled,
    inputRef,
    onChange,
}: {
    field: (typeof FIELDS)[number]
    value: string
    missing: boolean
    disabled: boolean
    inputRef: RefObject<HTMLInputElement>
    onChange: (value: string) => void
}): JSX.Element {
    const id = `bets-build-${field.name}`
    return (
        <Field>
            <FieldLabel htmlFor={id}>{field.label}</FieldLabel>
            <InputGroup>
                <InputGroupInput
                    ref={inputRef}
                    id={id}
                    inputMode={field.name === 'mde' ? 'decimal' : 'numeric'}
                    autoComplete="off"
                    value={value}
                    disabled={disabled}
                    onChange={(event) => onChange(event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
                            event.preventDefault()
                            onChange(stepValue(value, field.name, event.key === 'ArrowUp' ? 1 : -1))
                        }
                    }}
                    placeholder={field.placeholder}
                    data-attr={`bets-plan-${field.name}`}
                />
                <InputGroupAddon align="inline-end">
                    <InputGroupText>{field.unit}</InputGroupText>
                </InputGroupAddon>
            </InputGroup>
            <FieldDescription>{missing ? MISSING_AUDIENCE : field.help}</FieldDescription>
        </Field>
    )
}

export function BetBuildDialog({ bet }: { bet: BetsDetailApi }): JSX.Element {
    const { buildDialogIdea, buildDialogOpen, ideaPlans, busy, busyOperation, buildDisabledReason, ideaError } =
        useValues(betLogic({ id: bet.id }))
    const { openBuild, buildIdea, editPlan } = useActions(betLogic({ id: bet.id }))
    const refs: Record<PlanField, RefObject<HTMLInputElement>> = {
        audience: useRef<HTMLInputElement>(null),
        mde: useRef<HTMLInputElement>(null),
        days: useRef<HTMLInputElement>(null),
    }
    const buildRef = useRef<HTMLButtonElement>(null)
    const item = bet.work.find((entry) => entry.id === buildDialogIdea)
    const plan = item ? ideaPlans[item.id] : undefined
    const building = !!item && busyOperation === `work:${item.id}:build`
    const reason = buildDisabledReason ?? plan?.disabledReason ?? null
    const firstNeeded = plan?.audienceMissing ? refs.audience : plan?.disabledReason ? refs.days : buildRef
    return (
        <Dialog
            open={buildDialogOpen && !!item}
            onOpenChange={(open) => {
                if (!open && !building) {
                    openBuild(null)
                }
            }}
        >
            {item && (
                <DialogContent
                    className="Today__page Bets BetBuildDialog"
                    initialFocus={firstNeeded}
                    data-attr="bets-build-dialog"
                >
                    <form
                        className="contents"
                        onSubmit={(event) => {
                            event.preventDefault()
                            if (!reason && !busy) {
                                buildIdea(item.id)
                            }
                        }}
                    >
                        <DialogHeader>
                            <DialogTitle>Build this idea</DialogTitle>
                            <DialogDescription>{item.title}</DialogDescription>
                        </DialogHeader>
                        <DialogBody>
                            {plan ? (
                                <div className="flex flex-col gap-4">
                                    <Text size="sm" variant="muted" render={<p className="m-0" />}>
                                        Bets builds the change behind a flag and tests it with this plan.
                                    </Text>
                                    {FIELDS.map((field) => (
                                        <PlanFieldRow
                                            key={field.name}
                                            field={field}
                                            value={plan.draft[field.name]}
                                            missing={field.name === 'audience' && plan.audienceMissing}
                                            disabled={building}
                                            inputRef={refs[field.name]}
                                            onChange={(value) => editPlan(item.id, item.plan, field.name, value)}
                                        />
                                    ))}
                                    {plan.warnings.length > 0 && (
                                        <div className="flex flex-col gap-1" aria-live="polite">
                                            {plan.warnings.map((warning) => (
                                                <Text
                                                    key={warning}
                                                    size="xs"
                                                    variant="muted"
                                                    render={<p className="m-0 flex items-start gap-1.5" />}
                                                >
                                                    <IconInfo
                                                        className="BetBuildDialog__warningIcon shrink-0"
                                                        aria-hidden
                                                    />
                                                    {warning}
                                                </Text>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            ) : (
                                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                                    Bets builds the change behind a flag and plans the test when it goes live.
                                </Text>
                            )}
                            {ideaError && (
                                <Text size="sm" variant="destructive" role="alert" render={<p className="m-0 mt-3" />}>
                                    {ideaError}
                                </Text>
                            )}
                        </DialogBody>
                        <DialogFooter>
                            <Button
                                type="button"
                                variant="outline"
                                disabled={building}
                                onClick={() => openBuild(null)}
                                data-attr="bets-build-cancel"
                            >
                                Cancel
                            </Button>
                            <Button
                                ref={buildRef}
                                type="submit"
                                variant="primary"
                                loading={building}
                                disabled={busy && !building}
                                disabledReason={reason ?? undefined}
                                data-attr="bets-build-confirm"
                            >
                                Build
                            </Button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            )}
        </Dialog>
    )
}
