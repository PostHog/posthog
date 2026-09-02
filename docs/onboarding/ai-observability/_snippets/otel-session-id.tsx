import { OnboardingComponentsContext } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../../steps'

export interface OtelSessionIdConfig {
    /** Language tabs the surrounding page shows, in the order it shows them. */
    languages: ('Python' | 'Node')[]
}

const PYTHON_CODE = `
import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Optional

from opentelemetry.context import Context
from opentelemetry.sdk.trace import Span, SpanProcessor

session_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "ai_session_id", default=None
)


class SessionIdSpanProcessor(SpanProcessor):
    def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
        session_id = session_id_var.get()
        if session_id is not None:
            span.set_attribute("$ai_session_id", session_id)


@contextmanager
def ai_session(session_id: str) -> Iterator[None]:
    token = session_id_var.set(session_id)
    try:
        yield
    finally:
        session_id_var.reset(token)


# Register it on the same provider as PostHogSpanProcessor
provider.add_span_processor(SessionIdSpanProcessor())

# Resetting on exit keeps the ID off the next request that reuses this thread
with ai_session("conversation-abc"):
    reply = handle_turn(user_message)
`.trim()

const NODE_CODE = `
import { AsyncLocalStorage } from 'node:async_hooks'
import type { Span, SpanProcessor } from '@opentelemetry/sdk-trace-base'

const sessionStore = new AsyncLocalStorage<string>()

class SessionIdSpanProcessor implements SpanProcessor {
  onStart(span: Span): void {
    const sessionId = sessionStore.getStore()
    if (sessionId) {
      span.setAttribute('$ai_session_id', sessionId)
    }
  }
  onEnd(): void {}
  async shutdown(): Promise<void> {}
  async forceFlush(): Promise<void> {}
}

// Every span started inside the callback carries this session ID
const reply = await sessionStore.run('conversation-abc', () => handleTurn(userMessage))
`.trim()

const CODE_BY_LANGUAGE = {
    Python: { language: 'python', file: 'Python', code: PYTHON_CODE },
    Node: { language: 'typescript', file: 'Node', code: NODE_CODE },
}

export const getOtelSessionIdStep = (ctx: OnboardingComponentsContext, config: OtelSessionIdConfig): StepDefinition => {
    const { CodeBlock, Markdown, dedent } = ctx

    return {
        title: 'Group traces into sessions',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        PostHog groups traces into a session when they share an \`$ai_session_id\`. Set it if your
                        product has multi-turn conversations, so the Sessions tab can reconstruct them. Workloads
                        that finish in a single trace, like batch jobs or one-shot generation, do not need it.

                        The instrumentation creates the LLM span for you, so there is no call to pass the session ID
                        to. Add a span processor that sets the \`$ai_session_id\` attribute as each span starts.
                        PostHog forwards span attributes it does not recognize onto the event, so the value arrives
                        as the \`$ai_session_id\` property.
                    `}
                </Markdown>

                <CodeBlock blocks={config.languages.map((language) => CODE_BY_LANGUAGE[language])} />

                {config.languages.includes('Node') && (
                    <Markdown>
                        {dedent`
                            On Node, add \`new SessionIdSpanProcessor()\` to the \`spanProcessors\` array of the
                            \`NodeSDK\` you configured earlier, next to \`PostHogSpanProcessor\`. Keep the rest of
                            that setup as it is, including \`instrumentations\` and the \`sdk.start()\` call.
                        `}
                    </Markdown>
                )}

                <Markdown>
                    {dedent`
                        If a process only ever handles one session, set \`$ai_session_id\` as a resource attribute
                        next to \`service.name\` instead. Resource attributes apply to every span the process emits,
                        so that only works when the process and the session are the same thing.
                    `}
                </Markdown>
            </>
        ),
    }
}
