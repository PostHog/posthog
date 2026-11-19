import './questionnaire.css'

import {
    Questionnaire as QuestionnairePrimitive,
    type QuestionnaireChoiceDefinition,
    type QuestionnaireInputType,
    type QuestionnaireItemDefinition,
    type QuestionnaireItemStatus,
    type QuestionnaireShortcutMode,
} from '@shadcn/react/questionnaire'
import { mergeProps } from '@base-ui/react/merge-props'
import { CheckIcon } from 'lucide-react'
import * as React from 'react'

import { Button, buttonVariants } from '../button'
import { InputGroup, InputGroupAddon, InputGroupInput } from '../input-group'
import { cn } from '../lib/utils'

/**
 * A run of questions asked one at a time — the form an agent puts up when it needs the user to
 * decide before it can carry on. Quill wrapper over the headless `@shadcn/react/questionnaire`
 * engine, which owns ordering, the active item, answers, validation, progress, navigation, and the
 * answer shortcuts.
 *
 * What the engine leaves to the surface around it: closing, persistence, transport, and branching.
 * So a questionnaire in a dialog still gets its cancel button from the dialog, and a conditional
 * question is `disabled` by the app off an earlier answer rather than by a prop here.
 *
 * The root is a real `form` and each item a `fieldset` whose legend is the question, so answers come
 * back through `FormData` — `get(name)` for one, `getAll(name)` for `multiple`. Fixed choices are
 * native radios and checkboxes under an invisible overlay, which is what keeps arrow-key roving and
 * form participation working while the whole row stays the hit target.
 */
const Questionnaire = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Root>,
    React.ComponentProps<typeof QuestionnairePrimitive.Root>
>(function Questionnaire({ className, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Root
            ref={ref}
            data-quill
            data-slot="questionnaire"
            className={cn('quill-questionnaire', className)}
            {...props}
        />
    )
})

/** `Question 2 of 5` by default; pass children to word it differently. */
const QuestionnaireProgress = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Progress>,
    React.ComponentProps<typeof QuestionnairePrimitive.Progress>
>(function QuestionnaireProgress({ className, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Progress
            ref={ref}
            data-slot="questionnaire-progress"
            className={cn('quill-questionnaire__progress', className)}
            {...props}
        />
    )
})

/**
 * One question. `name` is the key its answer arrives under and must be unique in the root. Only the
 * active item is rendered visibly — the engine hides and inerts the rest, so all of them can stay
 * mounted and keep their answers.
 */
const QuestionnaireItem = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Item>,
    React.ComponentProps<typeof QuestionnairePrimitive.Item>
>(function QuestionnaireItem({ className, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Item
            ref={ref}
            data-slot="questionnaire-item"
            className={cn('quill-questionnaire__item', className)}
            {...props}
        />
    )
})

const QuestionnaireTitle = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Title>,
    React.ComponentProps<typeof QuestionnairePrimitive.Title>
>(function QuestionnaireTitle({ className, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Title
            ref={ref}
            data-slot="questionnaire-title"
            className={cn('quill-questionnaire__title', className)}
            {...props}
        />
    )
})

const QuestionnaireDescription = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Description>,
    React.ComponentProps<typeof QuestionnairePrimitive.Description>
>(function QuestionnaireDescription({ className, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Description
            ref={ref}
            data-slot="questionnaire-description"
            className={cn('quill-questionnaire__description', className)}
            {...props}
        />
    )
})

const QuestionnaireChoices = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Choices>,
    React.ComponentProps<typeof QuestionnairePrimitive.Choices>
>(function QuestionnaireChoices({ className, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Choices
            ref={ref}
            data-slot="questionnaire-choices"
            className={cn('quill-questionnaire__choices', className)}
            {...props}
        />
    )
})

/**
 * One fixed answer. The row assembles its own parts — the overlaid control, the indicator, the label
 * children, and the shortcut key — so a caller only writes the answer's text. The indicator draws
 * itself off the row's `data-type`: a dot for a radio, a check for a checkbox.
 */
// Annotated so the emitted .d.ts names the public `typeof` instead of the package's private props chunk.
const QuestionnaireChoice: React.ForwardRefExoticComponent<
    React.ComponentPropsWithoutRef<typeof QuestionnairePrimitive.Choice> &
        React.RefAttributes<React.ComponentRef<typeof QuestionnairePrimitive.Choice>>
> = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Choice>,
    React.ComponentProps<typeof QuestionnairePrimitive.Choice>
>(function QuestionnaireChoice({ children, className, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Choice
            ref={ref}
            data-slot="questionnaire-choice"
            className={cn('quill-questionnaire__choice', className)}
            {...props}
        >
            <QuestionnairePrimitive.ChoiceInput
                data-slot="questionnaire-choice-input"
                className="quill-questionnaire__choice-input"
            />
            <span
                aria-hidden="true"
                data-slot="questionnaire-choice-indicator"
                className="quill-questionnaire__choice-indicator"
            >
                <span
                    data-slot="questionnaire-choice-indicator-dot"
                    className="quill-questionnaire__choice-indicator-dot"
                />
                <CheckIcon
                    data-slot="questionnaire-choice-indicator-check"
                    className="quill-questionnaire__choice-indicator-check"
                />
            </span>
            <QuestionnairePrimitive.ChoiceLabel
                data-slot="questionnaire-choice-label"
                className="quill-questionnaire__choice-label"
            >
                {children}
            </QuestionnairePrimitive.ChoiceLabel>
            <QuestionnairePrimitive.ChoiceShortcut
                data-slot="questionnaire-choice-shortcut"
                className={cn(
                    buttonVariants({ variant: 'outline', size: 'xs' }),
                    'quill-questionnaire__choice-shortcut'
                )}
            />
        </QuestionnairePrimitive.Choice>
    )
})

/** The muted second line of an answer — what picking it means. */
const QuestionnaireChoiceDescription = React.forwardRef<HTMLSpanElement, React.ComponentProps<'span'>>(
    function QuestionnaireChoiceDescription({ className, ...props }, ref) {
        return (
            <span
                ref={ref}
                data-slot="questionnaire-choice-description"
                className={cn('quill-questionnaire__choice-description', className)}
                {...props}
            />
        )
    }
)

/**
 * A freeform answer alongside the fixed ones. It takes its `name` from the item, so it competes with
 * the choices rather than adding to them. It always needs an accessible name — a placeholder is not
 * a label, so pass `aria-label` or point `aria-labelledby` at a visible one.
 *
 * It wears a choice's indicator and fills it once there's text, so the row reads as the answer it is
 * rather than a field that happens to sit under the answers. The indicator takes its shape from the
 * choices beside it — round for radios, square for checkboxes.
 */
// Annotated so the emitted .d.ts names the public `typeof` instead of the package's private props chunk.
const QuestionnaireInput: React.ForwardRefExoticComponent<
    React.ComponentPropsWithoutRef<typeof QuestionnairePrimitive.Input> &
        React.RefAttributes<React.ComponentRef<typeof QuestionnairePrimitive.Input>>
> = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Input>,
    React.ComponentProps<typeof QuestionnairePrimitive.Input>
>(function QuestionnaireInput({ className, render, ...props }, ref) {
    return (
        <div data-slot="questionnaire-input-wrapper" className="quill-questionnaire__input-wrapper">
            <QuestionnairePrimitive.Input
                ref={ref}
                data-slot="questionnaire-input"
                className={className}
                render={
                    render ??
                    ((inputProps) => (
                        <InputGroup
                            data-slot="questionnaire-input-group"
                            /* Otherwise only the text dims and the indicator stays at full strength. */
                            aria-disabled={inputProps.disabled ? true : undefined}
                            /*
                             * The engine gives the field a `name` only while it is the answer — `filled`
                             * would keep the indicator on after a choice took the answer back off it.
                             */
                            data-filled={inputProps.name !== undefined || undefined}
                            className="quill-questionnaire__input-group"
                        >
                            <InputGroupAddon align="inline-start">
                                <span
                                    aria-hidden="true"
                                    data-slot="questionnaire-input-indicator"
                                    className="quill-questionnaire__input-indicator"
                                >
                                    <span className="quill-questionnaire__input-indicator-dot" />
                                    <CheckIcon className="quill-questionnaire__input-indicator-check" />
                                </span>
                            </InputGroupAddon>
                            <InputGroupInput {...inputProps} />
                        </InputGroup>
                    ))
                }
                {...props}
            />
        </div>
    )
})

/** The engine's own message by default; pass children for a question-specific one. */
const QuestionnaireError = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Error>,
    React.ComponentProps<typeof QuestionnairePrimitive.Error>
>(function QuestionnaireError({ className, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Error
            ref={ref}
            data-slot="questionnaire-error"
            className={cn('quill-questionnaire__error', className)}
            {...props}
        />
    )
})

/** Layout only — the row Previous, Skip, and Next/Submit sit in. It holds no state. */
const QuestionnaireActions = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(
    function QuestionnaireActions({ className, ...props }, ref) {
        return (
            <div
                ref={ref}
                data-slot="questionnaire-actions"
                className={cn('quill-questionnaire__actions', className)}
                {...props}
            />
        )
    }
)

const QuestionnairePrevious = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Previous>,
    React.ComponentProps<typeof QuestionnairePrimitive.Previous>
>(function QuestionnairePrevious({ children, className, render, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Previous
            ref={ref}
            data-slot="questionnaire-previous"
            className={cn('quill-questionnaire__previous', className)}
            render={render ?? <Button variant="outline" />}
            {...props}
        >
            {children ?? 'Previous'}
        </QuestionnairePrimitive.Previous>
    )
})

const QuestionnaireSkip = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Skip>,
    React.ComponentProps<typeof QuestionnairePrimitive.Skip>
>(function QuestionnaireSkip({ children, className, render, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Skip
            ref={ref}
            data-slot="questionnaire-skip"
            className={cn('quill-questionnaire__skip', className)}
            render={render ?? <Button variant="outline" />}
            {...props}
        >
            {children ?? 'Skip'}
        </QuestionnairePrimitive.Skip>
    )
})

type AdvanceRender = React.ComponentProps<typeof QuestionnairePrimitive.Submit>['render']

/**
 * Next and Submit stay disabled while the active question is unanswered. The engine refuses an unanswered
 * question on submit anyway, optional ones included (Skip is their way past), so a live button there only
 * invites a click that fails. A keyboard submit still runs the engine's validation and shows the error.
 */
function disabledUntilAnswered(render: AdvanceRender): NonNullable<AdvanceRender> {
    return (props, state) => {
        const gated = { ...props, disabled: props.disabled || state.status === 'unanswered' }
        if (typeof render === 'function') {
            return render(gated, state)
        }
        const element = render ?? <Button variant="primary" />
        return React.cloneElement(element, mergeProps(element.props as React.ComponentProps<'button'>, gated))
    }
}

const QuestionnaireNext = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Next>,
    React.ComponentProps<typeof QuestionnairePrimitive.Next>
>(function QuestionnaireNext({ children, className, render, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Next
            ref={ref}
            data-slot="questionnaire-next"
            className={cn('quill-questionnaire__next', className)}
            render={disabledUntilAnswered(render)}
            {...props}
        >
            {children ?? 'Next'}
        </QuestionnairePrimitive.Next>
    )
})

const QuestionnaireSubmit = React.forwardRef<
    React.ComponentRef<typeof QuestionnairePrimitive.Submit>,
    React.ComponentProps<typeof QuestionnairePrimitive.Submit>
>(function QuestionnaireSubmit({ children, className, render, ...props }, ref) {
    return (
        <QuestionnairePrimitive.Submit
            ref={ref}
            data-slot="questionnaire-submit"
            className={cn('quill-questionnaire__submit', className)}
            render={disabledUntilAnswered(render)}
            {...props}
        >
            {children ?? 'Submit'}
        </QuestionnairePrimitive.Submit>
    )
})

export {
    Questionnaire,
    QuestionnaireActions,
    QuestionnaireChoice,
    QuestionnaireChoiceDescription,
    QuestionnaireChoices,
    QuestionnaireDescription,
    QuestionnaireError,
    QuestionnaireInput,
    QuestionnaireItem,
    QuestionnaireNext,
    QuestionnairePrevious,
    QuestionnaireProgress,
    QuestionnaireSkip,
    QuestionnaireSubmit,
    QuestionnaireTitle,
    type QuestionnaireChoiceDefinition,
    type QuestionnaireInputType,
    type QuestionnaireItemDefinition,
    type QuestionnaireItemStatus,
    type QuestionnaireShortcutMode,
}
