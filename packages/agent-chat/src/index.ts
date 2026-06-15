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

export { Markdown } from './components/Markdown'

export { Labeled, PartRenderer, ThinkingPart, ToolCallCard } from './components/parts'
export type { ClientToolOutcome, PartRendererProps, PartTextVariant, ToolCallCardProps } from './components/parts'

export { describeContext, getStarterPrompts } from './context'
export type { ChatContext, ConciergePageContext, StarterPrompt } from './context'

// `useFakeRunner` is intentionally *not* exported from the main entry —
// it lives under `@posthog/agent-chat/fixtures` so production paths
// can't accidentally pull mock script handling into the runtime bundle.

export { isRenderHandler } from './types'
export type {
    AgentApplicationRef,
    AssistantTurn,
    AssistantTurnPart,
    ChatSession,
    ClientToolHandler,
    ClientToolRenderCallbacks,
    ClientToolRenderHandler,
    ClientToolSyncHandler,
    FocusArgs,
    FocusResult,
    PendingApproval,
    SessionPrincipal,
    SessionState,
    SessionTrigger,
    SessionTriggerKind,
    SessionUsage,
    ToastArgs,
    ToastResult,
    Turn,
    UserTurn,
} from './types'
