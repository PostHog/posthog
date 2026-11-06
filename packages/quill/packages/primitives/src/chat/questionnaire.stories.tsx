import type { Meta, StoryObj } from '@storybook/react'
import { CheckIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from '../button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader } from '../card'
import {
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '../dialog'
import { cn } from '../lib/utils'
import { Progress } from '../progress'
import { Tabs, TabsList, TabsTrigger } from '../tabs'
import { Text } from '../text'
import {
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
    type QuestionnaireItemStatus,
} from './questionnaire'

const meta: Meta<typeof Questionnaire> = {
    title: 'Primitives/Chat/Questionnaire',
    component: Questionnaire,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

type Question = {
    name: string
    prompt: string
    description?: string
    required?: boolean
    disabled?: boolean
    multiple?: boolean
    choices: readonly { value: string; label: string; description?: string; disabled?: boolean }[]
    input?: { label: string; placeholder: string }
}

const QUESTIONS: readonly Question[] = [
    {
        name: 'direction',
        required: true,
        prompt: 'What should we prototype next?',
        description: 'Choose a direction or write your own.',
        choices: [
            { value: 'delegation', label: 'Delegation', description: 'Show how work moves to a specialist.' },
            { value: 'questions', label: 'Question prompts', description: 'Show choices while the interface waits.' },
            { value: 'both', label: 'Both together' },
        ],
        input: { label: 'Another answer', placeholder: 'Type another answer…' },
    },
    {
        name: 'detail',
        prompt: 'How much detail should it include?',
        description: 'Skip this if you are not sure yet.',
        choices: [
            { value: 'focused', label: 'Focused' },
            { value: 'complete', label: 'Complete flow' },
        ],
    },
]

/**
 * The whole run of questions, mapped from one collection. `items` is what lets the engine render the
 * active item, the progress, the actions, and the shortcut keys on the first paint rather than after
 * a client-side pass.
 */
function Questions({
    questions,
    onStatusChange,
}: {
    questions: readonly Question[]
    onStatusChange?: (name: string, status: QuestionnaireItemStatus) => void
}): React.ReactElement {
    return (
        <>
            {questions.map((question) => (
                <QuestionnaireItem
                    key={question.name}
                    name={question.name}
                    required={question.required}
                    disabled={question.disabled}
                    multiple={question.multiple}
                    onStatusChange={onStatusChange ? (status) => onStatusChange(question.name, status) : undefined}
                >
                    <QuestionnaireTitle>{question.prompt}</QuestionnaireTitle>
                    {question.description ? (
                        <QuestionnaireDescription>{question.description}</QuestionnaireDescription>
                    ) : null}
                    <QuestionnaireChoices>
                        {question.choices.map((choice) => (
                            <QuestionnaireChoice key={choice.value} value={choice.value} disabled={choice.disabled}>
                                {choice.label}
                                {choice.description ? (
                                    <QuestionnaireChoiceDescription>
                                        {choice.description}
                                    </QuestionnaireChoiceDescription>
                                ) : null}
                            </QuestionnaireChoice>
                        ))}
                        {question.input ? (
                            <QuestionnaireInput
                                aria-label={question.input.label}
                                placeholder={question.input.placeholder}
                            />
                        ) : null}
                    </QuestionnaireChoices>
                    <QuestionnaireError />
                </QuestionnaireItem>
            ))}
        </>
    )
}

/** Reads the answers back out of the form the way an app would, so the stories can show them. */
function readAnswers(form: HTMLFormElement, questions: readonly Question[]): Record<string, string[]> {
    const data = new FormData(form)
    return Object.fromEntries(questions.map((question) => [question.name, data.getAll(question.name).map(String)]))
}

function Answers({ answers }: { answers: Record<string, string[]> | null }): React.ReactElement | null {
    if (!answers) {
        return null
    }
    return (
        <Text size="xs" variant="muted" render={<pre />}>
            {JSON.stringify(answers, null, 2)}
        </Text>
    )
}

/**
 * The default shape: progress on top, one question at a time, navigation pinned to the bottom row.
 * Answers arrive through `FormData` on submit — the engine never holds them for the app.
 */
export const Default: Story = {
    render: () => {
        function Demo(): React.ReactElement {
            const [answers, setAnswers] = React.useState<Record<string, string[]> | null>(null)

            return (
                <div className="flex w-full max-w-sm flex-col gap-4">
                    <Questionnaire
                        items={QUESTIONS}
                        onSubmit={(event) => {
                            event.preventDefault()
                            setAnswers(readAnswers(event.currentTarget, QUESTIONS))
                        }}
                    >
                        <QuestionnaireProgress />
                        <Questions questions={QUESTIONS} />
                        <QuestionnaireActions>
                            <QuestionnairePrevious />
                            <QuestionnaireSkip />
                            <QuestionnaireNext />
                            <QuestionnaireSubmit />
                        </QuestionnaireActions>
                    </Questionnaire>
                    <Answers answers={answers} />
                </div>
            )
        }
        return <Demo />
    },
}

const MULTIPLE: readonly Question[] = [
    {
        name: 'signals',
        required: true,
        multiple: true,
        prompt: 'Which signals should the agent watch?',
        description: 'Pick as many as apply.',
        choices: [
            { value: 'errors', label: 'Errors', description: 'New and reopened exceptions.' },
            { value: 'latency', label: 'Latency', description: 'Slow endpoints and queries.' },
            { value: 'spend', label: 'Spend', description: 'Cost per user and per model.' },
            { value: 'churn', label: 'Churn risk' },
        ],
    },
]

/** `multiple` swaps the radios for checkboxes, and the answer comes back as a list. */
export const MultipleSelection: Story = {
    render: () => (
        <div className="w-full max-w-sm">
            <Questionnaire items={MULTIPLE}>
                <QuestionnaireProgress />
                <Questions questions={MULTIPLE} />
                <QuestionnaireActions>
                    <QuestionnairePrevious />
                    <QuestionnaireSubmit />
                </QuestionnaireActions>
            </Questionnaire>
        </div>
    ),
}

const FREEFORM: readonly Question[] = [
    {
        name: 'audience',
        required: true,
        prompt: 'Who is this dashboard for?',
        description: 'Choose an audience or describe your own.',
        choices: [
            { value: 'engineering', label: 'Engineering' },
            { value: 'growth', label: 'Growth' },
            { value: 'support', label: 'Support' },
        ],
        input: { label: 'Another audience', placeholder: 'Describe the audience…' },
    },
]

/**
 * The freeform field sits inside the choices rather than after them, so "or write your own" reads as
 * one more row. It shares the item's name, so typing in it replaces whatever choice was picked.
 */
export const FreeformAnswer: Story = {
    render: () => (
        <div className="w-full max-w-sm">
            <Questionnaire items={FREEFORM}>
                <QuestionnaireProgress />
                <Questions questions={FREEFORM} />
                <QuestionnaireActions>
                    <QuestionnaireSubmit />
                </QuestionnaireActions>
            </Questionnaire>
        </div>
    ),
}

const OPTIONAL: readonly Question[] = [
    {
        name: 'scope',
        required: true,
        prompt: 'What should the migration cover?',
        choices: [
            { value: 'schema', label: 'Schema only' },
            { value: 'schema-data', label: 'Schema and data' },
        ],
    },
    {
        name: 'window',
        prompt: 'When should it run?',
        description: 'Skip this and we will pick the next quiet window.',
        choices: [
            { value: 'now', label: 'As soon as it is ready' },
            { value: 'overnight', label: 'Overnight' },
        ],
    },
]

/**
 * An optional item still has to be resolved — answered or skipped — before navigation moves on, so
 * "no answer" is a decision the transcript records rather than a gap.
 */
export const ExplicitSkip: Story = {
    render: () => (
        <div className="w-full max-w-sm">
            <Questionnaire items={OPTIONAL} defaultItem="window">
                <QuestionnaireProgress />
                <Questions questions={OPTIONAL} />
                <QuestionnaireActions>
                    <QuestionnairePrevious />
                    <QuestionnaireSkip />
                    <QuestionnaireNext />
                    <QuestionnaireSubmit />
                </QuestionnaireActions>
            </Questionnaire>
        </div>
    ),
}

/** `shortcuts` puts a key on every answer — `letters` for A–Z, `numbers` for 1–9. */
export const Shortcuts: Story = {
    render: () => {
        function Demo(): React.ReactElement {
            const [mode, setMode] = React.useState<'letters' | 'numbers' | undefined>('letters')

            return (
                <div className="flex w-full max-w-sm flex-col gap-4">
                    <div className="flex gap-2">
                        <Button variant={mode === undefined ? 'primary' : 'outline'} onClick={() => setMode(undefined)}>
                            None
                        </Button>
                        <Button variant={mode === 'letters' ? 'primary' : 'outline'} onClick={() => setMode('letters')}>
                            Letters
                        </Button>
                        <Button variant={mode === 'numbers' ? 'primary' : 'outline'} onClick={() => setMode('numbers')}>
                            Numbers
                        </Button>
                    </div>
                    <Questionnaire items={MULTIPLE} shortcuts={mode}>
                        <QuestionnaireProgress />
                        <Questions questions={MULTIPLE} />
                        <QuestionnaireActions>
                            <QuestionnaireSubmit />
                        </QuestionnaireActions>
                    </Questionnaire>
                </div>
            )
        }
        return <Demo />
    },
}

/**
 * Controlled navigation: the app owns which item is active, so it can send the user back to one that
 * failed its own checks and put the reason under it.
 */
export const CustomValidation: Story = {
    render: () => {
        function Demo(): React.ReactElement {
            const [item, setItem] = React.useState('scope')
            const [error, setError] = React.useState<string | null>(null)

            return (
                <div className="w-full max-w-sm">
                    <Questionnaire
                        items={OPTIONAL}
                        item={item}
                        onItemChange={setItem}
                        onSubmit={(event) => {
                            event.preventDefault()
                            const answers = readAnswers(event.currentTarget, OPTIONAL)
                            // Data migrations can't run in the quiet window, so this pair is invalid together.
                            if (answers.scope[0] === 'schema-data' && answers.window[0] === 'overnight') {
                                setError('Data migrations need a supervised window. Run it as soon as it is ready.')
                                setItem('window')
                                return
                            }
                            setError(null)
                        }}
                    >
                        <QuestionnaireProgress />
                        {OPTIONAL.map((question) => (
                            <QuestionnaireItem
                                key={question.name}
                                name={question.name}
                                required={question.required}
                                invalid={question.name === 'window' && error !== null}
                            >
                                <QuestionnaireTitle>{question.prompt}</QuestionnaireTitle>
                                {question.description ? (
                                    <QuestionnaireDescription>{question.description}</QuestionnaireDescription>
                                ) : null}
                                <QuestionnaireChoices>
                                    {question.choices.map((choice) => (
                                        <QuestionnaireChoice key={choice.value} value={choice.value}>
                                            {choice.label}
                                        </QuestionnaireChoice>
                                    ))}
                                </QuestionnaireChoices>
                                <QuestionnaireError>
                                    {question.name === 'window' && error ? error : undefined}
                                </QuestionnaireError>
                            </QuestionnaireItem>
                        ))}
                        <QuestionnaireActions>
                            <QuestionnairePrevious />
                            <QuestionnaireSkip />
                            <QuestionnaireNext />
                            <QuestionnaireSubmit />
                        </QuestionnaireActions>
                    </Questionnaire>
                </div>
            )
        }
        return <Demo />
    },
}

/**
 * A partly-filled run picked back up: `defaultItem` restores where the user left off and the choices
 * carry `defaultChecked` for what they had already answered.
 */
export const Resume: Story = {
    render: () => (
        <div className="w-full max-w-sm">
            <Questionnaire items={OPTIONAL} defaultItem="window">
                <QuestionnaireProgress />
                {OPTIONAL.map((question) => (
                    <QuestionnaireItem key={question.name} name={question.name} required={question.required}>
                        <QuestionnaireTitle>{question.prompt}</QuestionnaireTitle>
                        <QuestionnaireChoices>
                            {question.choices.map((choice) => (
                                <QuestionnaireChoice
                                    key={choice.value}
                                    value={choice.value}
                                    defaultChecked={question.name === 'scope' && choice.value === 'schema'}
                                >
                                    {choice.label}
                                </QuestionnaireChoice>
                            ))}
                        </QuestionnaireChoices>
                        <QuestionnaireError />
                    </QuestionnaireItem>
                ))}
                <QuestionnaireActions>
                    <QuestionnairePrevious />
                    <QuestionnaireSkip />
                    <QuestionnaireNext />
                    <QuestionnaireSubmit />
                </QuestionnaireActions>
            </Questionnaire>
        </div>
    ),
}

/**
 * Branching is the app's, not the engine's: a question that no longer applies is `disabled`, which
 * drops it out of the order, the progress count, and the validation pass.
 */
export const ConditionalItems: Story = {
    render: () => {
        function Demo(): React.ReactElement {
            const [scope, setScope] = React.useState<string | null>(null)
            const questions: readonly Question[] = [
                OPTIONAL[0],
                // Only worth asking about a window once data is in scope.
                { ...OPTIONAL[1], disabled: scope !== 'schema-data' },
            ]

            return (
                <div className="flex w-full max-w-sm flex-col gap-4">
                    <Questionnaire items={questions}>
                        <QuestionnaireProgress />
                        {questions.map((question) => (
                            <QuestionnaireItem
                                key={question.name}
                                name={question.name}
                                required={question.required}
                                disabled={question.disabled}
                            >
                                <QuestionnaireTitle>{question.prompt}</QuestionnaireTitle>
                                <QuestionnaireChoices>
                                    {question.choices.map((choice) => (
                                        <QuestionnaireChoice
                                            key={choice.value}
                                            value={choice.value}
                                            onChange={
                                                question.name === 'scope'
                                                    ? (event) => setScope(event.currentTarget.value)
                                                    : undefined
                                            }
                                        >
                                            {choice.label}
                                        </QuestionnaireChoice>
                                    ))}
                                </QuestionnaireChoices>
                                <QuestionnaireError />
                            </QuestionnaireItem>
                        ))}
                        <QuestionnaireActions>
                            <QuestionnairePrevious />
                            <QuestionnaireSkip />
                            <QuestionnaireNext />
                            <QuestionnaireSubmit />
                        </QuestionnaireActions>
                    </Questionnaire>
                    <Text size="xs" variant="muted">
                        {scope === 'schema-data'
                            ? 'Two questions — the window question applies.'
                            : 'One question — the window question is out of the run.'}
                    </Text>
                </div>
            )
        }
        return <Demo />
    },
}

/** Every navigation action exposes its state, so an app can word or gate them itself. */
export const NavigationState: Story = {
    render: () => (
        <div className="w-full max-w-sm">
            <Questionnaire items={QUESTIONS}>
                <QuestionnaireProgress />
                <Questions questions={QUESTIONS} />
                <QuestionnaireActions>
                    <QuestionnairePrevious>Back</QuestionnairePrevious>
                    <QuestionnaireSkip>Not now</QuestionnaireSkip>
                    <QuestionnaireNext
                        render={(props, state) => (
                            <Button {...props} variant="primary" disabled={state.status === 'unanswered'} />
                        )}
                    >
                        Continue
                    </QuestionnaireNext>
                    <QuestionnaireSubmit>Start building</QuestionnaireSubmit>
                </QuestionnaireActions>
            </Questionnaire>
        </div>
    ),
}

/** The progress part hands over `current`/`total`, so it can be a bar instead of a line of text. */
export const CustomProgress: Story = {
    render: () => (
        <div className="w-full max-w-sm">
            <Questionnaire items={QUESTIONS}>
                {/*
                 * The wrapper keeps the named progressbar and its `Question 1 of 2` value text, so the
                 * bar inside is decoration for the same number and is hidden from screen readers.
                 */}
                <QuestionnaireProgress
                    className="w-full min-w-0"
                    render={(props, state) => (
                        <div {...props}>
                            <Progress aria-hidden="true" value={(state.current / state.total) * 100} />
                        </div>
                    )}
                />
                <Questions questions={QUESTIONS} />
                <QuestionnaireActions>
                    <QuestionnairePrevious />
                    <QuestionnaireSkip />
                    <QuestionnaireNext />
                    <QuestionnaireSubmit />
                </QuestionnaireActions>
            </Questionnaire>
        </div>
    ),
}

/** Each question carries a short label for its tab, which the prompt is too long to be. */
type TabbedQuestion = Question & { tab: string }

const TABBED: readonly TabbedQuestion[] = [
    {
        name: 'source',
        tab: 'Source',
        required: true,
        prompt: 'Where should the data come from?',
        choices: [
            { value: 'warehouse', label: 'Data warehouse' },
            { value: 'events', label: 'Product events' },
        ],
    },
    {
        name: 'schedule',
        tab: 'Schedule',
        required: true,
        prompt: 'How often should it sync?',
        choices: [
            { value: 'hourly', label: 'Every hour' },
            { value: 'daily', label: 'Once a day' },
            { value: 'weekly', label: 'Once a week' },
        ],
    },
    {
        name: 'owner',
        tab: 'Owner',
        prompt: 'Who should own it?',
        description: 'Skip this and it stays unassigned.',
        choices: [
            { value: 'me', label: 'Me' },
            { value: 'team', label: 'The whole team' },
        ],
        input: { label: 'Someone else', placeholder: 'Name someone else…' },
    },
]

/**
 * Tabs as the way through the run: the whole set of questions is visible up front and any of them can
 * be answered in any order, which suits a short run the user is meant to survey before committing.
 *
 * The tabs and the questionnaire stay in step because both read the same `item` state — the engine's
 * own navigation moves it, and so does a tab. Each tab's check comes from the item's
 * `onStatusChange`, so it appears on `answered` and stays hidden for a question that was skipped.
 *
 * The tabs sit outside the form, which is why the card wraps the questionnaire rather than the other
 * way round. Inside the form they would be one more thing to tab through between the question and its
 * answers, and their buttons would take part in the form.
 */
export const TabbedNavigation: Story = {
    render: () => {
        function Demo(): React.ReactElement {
            const [item, setItem] = React.useState(TABBED[0].name)
            const [statuses, setStatuses] = React.useState<Record<string, QuestionnaireItemStatus>>({})

            return (
                <div className="w-full max-w-sm">
                    <Card className="pt-2" size="sm">
                        <CardHeader className="border-b px-2">
                            <Tabs value={item} onValueChange={(value) => setItem(String(value))}>
                                <TabsList variant="line">
                                    {TABBED.map((question) => {
                                        const answered = statuses[question.name] === 'answered'
                                        return (
                                            <TabsTrigger
                                                key={question.name}
                                                value={question.name}
                                                className={cn(answered ? 'bg-success/20' : '')}
                                            >
                                                {/* `invisible` rather than absent, so the label doesn't shift when it lands. */}
                                                <CheckIcon
                                                    aria-hidden="true"
                                                    className={
                                                        answered ? 'text-success-foreground' : 'text-foreground/20'
                                                    }
                                                />
                                                <span className={cn(answered ? 'text-success-foreground' : '')}>
                                                    {question.tab}
                                                </span>
                                                <span className="sr-only">
                                                    {answered ? ', answered' : ', unanswered'}
                                                </span>
                                            </TabsTrigger>
                                        )
                                    })}
                                </TabsList>
                            </Tabs>
                        </CardHeader>
                        {/* `contents` hands the card's content and footer back to the card's own layout. */}
                        <Questionnaire
                            className="contents"
                            items={TABBED}
                            item={item}
                            onItemChange={setItem}
                            onSubmit={(event) => event.preventDefault()}
                        >
                            <CardContent className="flex flex-col gap-4">
                                <Questions
                                    questions={TABBED}
                                    onStatusChange={(name, status) =>
                                        setStatuses((current) => ({ ...current, [name]: status }))
                                    }
                                />
                            </CardContent>
                            <CardFooter>
                                <QuestionnaireActions>
                                    <QuestionnairePrevious />
                                    <QuestionnaireSkip />
                                    <QuestionnaireNext />
                                    <QuestionnaireSubmit />
                                </QuestionnaireActions>
                            </CardFooter>
                        </Questionnaire>
                    </Card>
                </div>
            )
        }
        return <Demo />
    },
}

/**
 * In a card, the card's header carries the framing and the item's title stays the question — the
 * fieldset's legend is still the thing the reader is answering.
 */
export const InCard: Story = {
    render: () => (
        <div className="w-full max-w-sm">
            <Questionnaire items={QUESTIONS}>
                <Card>
                    <CardHeader>
                        <CardDescription>Two questions, then it starts working.</CardDescription>
                    </CardHeader>
                    <CardContent className="flex flex-col gap-4">
                        <QuestionnaireProgress />
                        <Questions questions={QUESTIONS} />
                    </CardContent>
                    <CardFooter>
                        <QuestionnaireActions>
                            <QuestionnairePrevious />
                            <QuestionnaireSkip />
                            <QuestionnaireNext />
                            <QuestionnaireSubmit />
                        </QuestionnaireActions>
                    </CardFooter>
                </Card>
            </Questionnaire>
        </div>
    ),
}

/**
 * In a dialog, cancelling and dismissing stay the dialog's — the questionnaire only owns getting from
 * the first question to the last.
 */
export const InDialog: Story = {
    render: () => (
        <Dialog>
            <DialogTrigger render={<Button variant="primary" />}>Set up agent</DialogTrigger>
            <DialogContent>
                {/*
                 * `contents` hands the header, body, and footer straight to the dialog's own grid, so
                 * they keep their padding and dividers while the form still wraps the submit button.
                 */}
                <Questionnaire items={QUESTIONS} className="contents">
                    <DialogHeader>
                        <DialogTitle>Set up your first agent</DialogTitle>
                    </DialogHeader>
                    <DialogBody viewportClassName="flex flex-col gap-4">
                        <QuestionnaireProgress />
                        <Questions questions={QUESTIONS} />
                    </DialogBody>
                    {/*
                     * No `QuestionnaireActions` here — the footer is already the button row, and
                     * nesting the actions grid inside it doubles the gap between Cancel and Next.
                     */}
                    <DialogFooter>
                        <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                        <QuestionnairePrevious />
                        <QuestionnaireSkip />
                        <QuestionnaireNext />
                        <QuestionnaireSubmit />
                    </DialogFooter>
                </Questionnaire>
            </DialogContent>
        </Dialog>
    ),
}
