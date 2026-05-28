/**
 * The dock's empty / pre-session view.
 *
 * Two-tier UX:
 *   1. A short contextual greeting that reflects what the user is
 *      looking at right now.
 *   2. A handful of starter-prompt chips. Clicking one sends it
 *      immediately — no pre-fill, no confirm. The intent is to make
 *      the first interaction one click.
 */

import type { ChatContext, StarterPrompt } from '../context'

interface WaitingStateProps {
    context: ChatContext
    starterPrompts: StarterPrompt[]
    onStart: (prompt: string) => void
}

export function WaitingState({ context, starterPrompts, onStart }: WaitingStateProps): React.ReactElement {
    const greeting = greetingFor(context)

    return (
        <div className="flex h-full flex-col items-stretch justify-center px-5 py-8">
            <div className="space-y-1.5 text-center">
                <p className="text-base font-medium leading-tight text-foreground">{greeting.line1}</p>
                <p className="text-sm leading-snug text-muted-foreground">{greeting.line2}</p>
            </div>
            {starterPrompts.length > 0 ? (
                <div className="mt-6 flex flex-col gap-1.5">
                    {starterPrompts.map((p) => (
                        <button
                            key={p.id}
                            type="button"
                            onClick={() => onStart(p.prompt)}
                            className="group flex w-full cursor-pointer items-start gap-2 rounded-md border border-border/60 bg-background px-3 py-2 text-left text-sm leading-snug transition-colors hover:border-foreground/30 hover:bg-accent focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                        >
                            <span className="mt-px text-xs text-muted-foreground transition-all group-hover:translate-x-0.5 group-hover:text-foreground">
                                →
                            </span>
                            <span>{p.label}</span>
                        </button>
                    ))}
                </div>
            ) : null}
        </div>
    )
}

function greetingFor(context: ChatContext): { line1: string; line2: string } {
    if (context.mode === 'playground') {
        return {
            line1: `Try ${context.agent.name}`,
            line2: 'You’re talking to the agent directly. Anything you send goes to it as a real user would.',
        }
    }
    switch (context.page.kind) {
        case 'agent-list':
            return { line1: 'How can I help?', line2: 'Ask about your agents, or describe one you want to build.' }
        case 'agent':
            return { line1: `Ask about ${context.page.agent.name}`, line2: 'Explain it, change it, or test it.' }
        case 'agent-bundle':
            return { line1: 'Ask about this bundle', line2: 'Skills, tools, instructions — I can read or edit any of it.' }
        case 'agent-revisions':
            return { line1: 'Compare or promote', line2: 'I can diff revisions, promote a draft, or branch a new one.' }
        case 'agent-sessions':
            return { line1: 'Ask about activity', line2: 'Recent sessions, errors, costs — I can summarize or dig in.' }
        case 'agent-session':
            return { line1: 'Ask about this session', line2: 'I can explain what happened or replay with a tweak.' }
        case 'unknown':
        default:
            return { line1: 'How can I help?', line2: 'I know about agents on this platform.' }
    }
}
