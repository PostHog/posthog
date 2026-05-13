import { useActions, useValues } from 'kea'

import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    cn,
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupTextarea,
    ScrollArea,
    Separator,
} from '@posthog/quill'

import { SceneExport } from 'scenes/sceneTypes'

import { founderModeLogic } from './founderModeLogic'

export function FounderModeBlank(): JSX.Element {
    const { steps, position, currentStep, currentSubStep, isFirstStep, isLastStep } = useValues(founderModeLogic)
    const { nextStep, previousStep, setStep } = useActions(founderModeLogic)

    return (
        <main
            className="fixed inset-0 top-[54px] flex bg-fill-highlight-100 p-4 overflow-hidden"
            style={{
                backgroundColor: '#fff',
                backgroundSize: '13px 13px',
                backgroundImage: 'radial-gradient(1px, var(--color-gray-400), var(--color-gray-50))',
            }}
        >
            <aside className="shadow w-80 shrink-0 border rounded-sm border-border bg-surface-primary overflow-hidden flex flex-col min-h-0">
                <header className="shrink-0 px-3 py-2 border-b border-border">
                    <div className="flex items-center gap-2">
                        <span className="inline-flex items-center justify-center w-4 h-4 rounded-full border border-text-primary bg-text-primary text-bg-primary text-[10px] leading-none shrink-0">
                            {position.stepIndex + 1}
                        </span>
                        <span className="text-xs font-semibold text-text-primary truncate">{currentStep.title}</span>
                        <span className="ml-auto text-[10px] text-text-secondary">
                            {position.stepIndex + 1}/{steps.length}
                        </span>
                    </div>
                    <ol className="mt-1 ml-6 flex flex-wrap gap-x-2 gap-y-0.5">
                        {currentStep.subSteps.map((subStep, subStepIndex) => {
                            const isSubCompleted = subStepIndex < position.subStepIndex
                            const isSubCurrent = subStepIndex === position.subStepIndex
                            return (
                                <li key={subStep.key}>
                                    <button
                                        type="button"
                                        onClick={() => setStep(position.stepIndex, subStepIndex)}
                                        className={cn(
                                            'text-[11px] cursor-pointer hover:opacity-80 transition-opacity',
                                            isSubCurrent && 'font-medium text-text-primary',
                                            isSubCompleted && 'text-text-secondary line-through',
                                            !isSubCurrent && !isSubCompleted && 'text-text-secondary'
                                        )}
                                    >
                                        {subStep.title}
                                    </button>
                                </li>
                            )
                        })}
                    </ol>
                </header>
                <ScrollArea className="flex-1 min-h-0" viewportClassName="px-3 py-3">
                    <ChatThread />
                </ScrollArea>
                <footer className="shrink-0 border-t border-border p-2">
                    <InputGroup>
                        <InputGroupTextarea placeholder="Write a comment..." />
                        <InputGroupAddon align="block-end">
                            <InputGroupButton variant="primary" size="sm" className="ml-auto">
                                Post
                            </InputGroupButton>
                        </InputGroupAddon>
                    </InputGroup>
                </footer>
            </aside>
            <section className="flex-1 flex items-center justify-center px-12 py-10 min-h-0">
                <Card className="w-full max-w-xl shadow border ">
                    <CardHeader>
                        <CardDescription>
                            Step {position.stepIndex + 1}.{position.subStepIndex + 1} · {currentStep.title}
                        </CardDescription>
                        <CardTitle>{currentSubStep.title}</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <p className="text-text-secondary">Hello world</p>
                    </CardContent>
                    <Separator />
                    <CardContent className="flex justify-between">
                        <Button variant="outline" onClick={previousStep} disabled={isFirstStep}>
                            Back
                        </Button>
                        <Button variant="primary" onClick={nextStep} disabled={isLastStep}>
                            Next
                        </Button>
                    </CardContent>
                </Card>
            </section>
        </main>
    )
}

interface ChatMessage {
    author: 'user' | 'agent'
    text: string
}

const DUMMY_MESSAGES: ChatMessage[] = [
    { author: 'agent', text: "Hey! What's the problem you're trying to solve?" },
    { author: 'user', text: 'Founders waste hours digging through analytics dashboards.' },
    { author: 'agent', text: 'Got it. Who feels that pain the most — solo founders, small teams?' },
    { author: 'user', text: "Solo founders and tiny teams who don't have a data person." },
    { author: 'agent', text: 'Nice. Want to sketch the smallest possible version we could ship?' },
    { author: 'user', text: 'Yeah — basically a chat that answers product questions from PostHog data.' },
    { author: 'agent', text: 'Perfect starting point. Let me write up the scope cuts.' },
    { author: 'agent', text: "Hey! What's the problem you're trying to solve?" },
    { author: 'user', text: 'Founders waste hours digging through analytics dashboards.' },
    { author: 'agent', text: 'Got it. Who feels that pain the most — solo founders, small teams?' },
    { author: 'user', text: "Solo founders and tiny teams who don't have a data person." },
    { author: 'agent', text: 'Nice. Want to sketch the smallest possible version we could ship?' },
    { author: 'user', text: 'Yeah — basically a chat that answers product questions from PostHog data.' },
    { author: 'agent', text: 'Perfect starting point. Let me write up the scope cuts.' },
]

function ChatThread(): JSX.Element {
    return (
        <div className="space-y-3">
            {DUMMY_MESSAGES.map((msg, idx) => (
                <div key={idx} className={cn('flex', msg.author === 'user' ? 'justify-end' : 'justify-start')}>
                    <div
                        className={cn(
                            'max-w-[80%] rounded-md px-3 py-2 text-xs leading-snug',
                            msg.author === 'user'
                                ? 'bg-text-primary text-bg-primary'
                                : 'bg-fill-highlight-100 text-text-primary'
                        )}
                    >
                        {msg.text}
                    </div>
                </div>
            ))}
        </div>
    )
}

export const scene: SceneExport = {
    component: FounderModeBlank,
    logic: founderModeLogic,
}
