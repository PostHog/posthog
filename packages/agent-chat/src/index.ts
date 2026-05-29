/**
 * Public surface of `@posthog/agent-chat`.
 *
 * Consumer apps import:
 *   - `<AgentChat />` for the ambient chat dock
 *   - `ChatContext` + `getStarterPrompts` for context-aware prompts
 *   - `ClientToolHandler<T>` + well-known argument/result types for
 *     typed handler implementations
 *   - Session / turn / event types for stories + tests
 *
 * Fixture data lives under `@posthog/agent-chat/fixtures` to keep the
 * runtime bundle lean.
 */

export { AgentChat } from './AgentChat'
export type { AgentChatProps, TransportError } from './AgentChat'

export { JsonView } from './components/JsonView'
export type { JsonViewProps } from './components/JsonView'

export { describeContext, getStarterPrompts } from './context'
export type { ChatContext, ConciergePageContext, StarterPrompt } from './context'

export { useFakeRunner } from './fake-runner'
export type { FakeRunnerControls, Script, ScriptStep, UseFakeRunnerOpts } from './fake-runner'

export type {
    AgentApplicationRef,
    AssistantTurn,
    AssistantTurnPart,
    ChatSession,
    ClientToolHandler,
    FocusArgs,
    FocusResult,
    PendingApproval,
    SessionPrincipal,
    SessionState,
    SessionTrigger,
    SessionUsage,
    ToastArgs,
    ToastResult,
    Turn,
    UserTurn,
} from './types'
