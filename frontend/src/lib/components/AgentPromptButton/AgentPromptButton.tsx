import { useState } from 'react'

import { IconCopy, IconLogomark, IconMagicWand } from '@posthog/icons'

import { useLocalStorage } from 'lib/hooks/useLocalStorage'
import { ButtonGroupPrimitive, ButtonPrimitive, type ButtonSize } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItemIndicator,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

import claudeLogo from './logos/claude.svg'
import cursorLogo from './logos/cursor.svg'
import openaiLogo from './logos/openai.svg'

export interface AgentPromptAction {
    /** Stable key used for localStorage persistence */
    key: string
    label: string
    icon?: React.ReactElement
    /** Returns the prompt text for this action */
    buildPrompt: () => string
}

export interface AgentPromptButtonProps {
    actions: AgentPromptAction[]
    /**
     * Namespace for the localStorage key that persists the remembered combo.
     * Pass a unique value per call-site to give that surface its own memory.
     * When omitted, defaults to a key derived from the sorted action keys, so
     * surfaces with the same action set share state and surfaces with different
     * actions stay isolated.
     */
    storageKey?: string
    size?: ButtonSize
    /** Renders the dropdown open on first paint. Useful for visual regression snapshots. */
    defaultOpen?: boolean
    'data-attr'?: string
}

interface RememberedCombo {
    actionKey: string
    agentKey: string | null
}

interface AgentDef {
    key: string
    name: string
    /** Either a brand SVG URL (string from `import foo from './logos/foo.svg'`) or a React node */
    logo: string | React.ReactElement
    /** Extra classes applied to the rendered <img> for brand SVG logos (e.g. `dark:invert` for monochrome marks) */
    logoClassName?: string
    /**
     * Builds the deeplink URL for this agent.
     * Some agents double-encode or truncate prompts due to URL length limits.
     */
    buildDeepLink: (prompt: string) => string
}

/** Max prompt chars before truncation for agents that have strict URL length limits. */
const LIMIT_LONG = 8_000
const LIMIT_CLAUDE_CODE = 5_000
const LIMIT_SHORT = 4_000

function withLimit(prompt: string, maxChars: number, build: (p: string) => string): string {
    return build(prompt.slice(0, maxChars))
}

const AGENTS: AgentDef[] = [
    {
        key: 'posthog-code',
        name: 'PostHog Code',
        logo: <IconLogomark className="size-4 shrink-0" />,
        buildDeepLink: (p) => `posthog-code://new?prompt=${encodeURIComponent(p)}`,
    },
    {
        key: 'claude-code',
        name: 'Claude Code',
        logo: claudeLogo,
        buildDeepLink: (p) => withLimit(p, LIMIT_CLAUDE_CODE, (t) => `claude://code/new?q=${encodeURIComponent(t)}`),
    },
    {
        key: 'cursor',
        name: 'Cursor',
        logo: cursorLogo,
        // Cursor wordmark is solid black; invert in dark mode so it stays visible
        logoClassName: 'dark:invert',
        buildDeepLink: (p) =>
            // Cursor decodes the full deeplink before parsing query params, so reserved chars need an extra escape layer.
            withLimit(
                p,
                LIMIT_LONG,
                (t) => `cursor://anysphere.cursor-deeplink/prompt?text=${encodeURIComponent(encodeURIComponent(t))}`
            ),
    },
    {
        key: 'codex',
        name: 'Codex',
        logo: openaiLogo,
        buildDeepLink: (p) => withLimit(p, LIMIT_SHORT, (t) => `codex://new?prompt=${encodeURIComponent(t)}`),
    },
]

/** Sentinel agentKey for the "Copy to clipboard" option. Stored alongside real agent keys. */
const CLIPBOARD_KEY = 'clipboard'

function invokeAgent(agent: AgentDef, prompt: string): void {
    window.open(agent.buildDeepLink(prompt), '_blank')
}

function AgentLogo({ agent }: { agent: AgentDef }): JSX.Element {
    if (typeof agent.logo !== 'string') {
        return agent.logo
    }
    return (
        <img
            src={agent.logo}
            alt=""
            aria-hidden
            className={cn('size-4 shrink-0 object-contain', agent.logoClassName)}
        />
    )
}

export function AgentPromptButton({
    actions,
    storageKey,
    size = 'sm',
    defaultOpen = false,
    'data-attr': dataAttr,
}: AgentPromptButtonProps): JSX.Element | null {
    const resolvedStorageKey =
        storageKey ??
        `agent-prompt-button:${actions
            .map((a) => a.key)
            .sort()
            .join(',')}`
    const [remembered, setRemembered] = useLocalStorage<RememberedCombo | null>(`${resolvedStorageKey}:combo`, null)
    const [open, setOpen] = useState(defaultOpen)

    if (actions.length === 0) {
        return null
    }

    const activeAction = (remembered ? actions.find((a) => a.key === remembered.actionKey) : null) ?? actions[0]
    const activeAgent = remembered?.agentKey ? (AGENTS.find((a) => a.key === remembered.agentKey) ?? null) : null
    const isClipboard = remembered?.agentKey === CLIPBOARD_KEY
    const hasTarget = !!activeAgent || isClipboard
    // Empty state and clipboard both render as "with AI"; a real agent name overrides it
    const targetName = activeAgent?.name ?? 'AI'
    const buttonLabel = `${activeAction.label} with ${targetName}`

    const selectAction = (actionKey: string): void => {
        setRemembered({ actionKey, agentKey: remembered?.agentKey ?? null })
    }

    const runCombo = (actionKey: string, agentKey: string): void => {
        const action = actions.find((a) => a.key === actionKey) ?? actions[0]
        const prompt = action.buildPrompt()
        if (agentKey === CLIPBOARD_KEY) {
            void copyToClipboard(prompt, `${action.label.toLowerCase()} prompt`)
            return
        }
        const agent = AGENTS.find((a) => a.key === agentKey)
        if (agent) {
            invokeAgent(agent, prompt)
        }
    }

    const selectAgent = (agentKey: string): void => {
        const actionKey = remembered?.actionKey ?? actions[0].key
        setRemembered({ actionKey, agentKey })
        setOpen(false)
        // Picking an agent is the action — saves it as the favorite and runs immediately.
        // The main button just re-runs the saved combo on subsequent clicks.
        runCombo(actionKey, agentKey)
    }

    const handleMainClick = (): void => {
        if (!hasTarget || !remembered?.agentKey) {
            setOpen(true)
            return
        }
        runCombo(remembered.actionKey, remembered.agentKey)
    }

    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <ButtonGroupPrimitive size={size} groupVariant="outline">
                <ButtonPrimitive
                    onClick={handleMainClick}
                    data-attr={dataAttr}
                    tooltip={hasTarget ? `Run: ${buttonLabel}` : 'Pick an agent first'}
                >
                    <IconMagicWand className="shrink-0" />
                    <span className="truncate max-w-64">{buttonLabel}</span>
                </ButtonPrimitive>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive iconOnly forceVariant variant="panel">
                        <MenuOpenIndicator direction="down" className="ml-0" />
                    </ButtonPrimitive>
                </DropdownMenuTrigger>
            </ButtonGroupPrimitive>

            <DropdownMenuContent align="end" className="w-56">
                {actions.length > 1 && (
                    <>
                        <DropdownMenuRadioGroup value={activeAction.key} onValueChange={selectAction}>
                            {actions.map((action) => (
                                <DropdownMenuRadioItem
                                    key={action.key}
                                    value={action.key}
                                    asChild
                                    onSelect={(e) => e.preventDefault()}
                                >
                                    <ButtonPrimitive menuItem className="gap-1.5">
                                        {action.icon}
                                        <span className="truncate flex-1">{action.label}</span>
                                        <DropdownMenuItemIndicator intent="radio" />
                                    </ButtonPrimitive>
                                </DropdownMenuRadioItem>
                            ))}
                        </DropdownMenuRadioGroup>
                        {/* Direct child of the padding-less menu inner — drop the separator's
                            default -mx-1 so it doesn't overflow and trigger scroll shadows */}
                        <DropdownMenuSeparator className="mx-0" />
                    </>
                )}
                <DropdownMenuLabel>Open in</DropdownMenuLabel>
                <DropdownMenuRadioGroup value={remembered?.agentKey ?? ''} onValueChange={selectAgent}>
                    {AGENTS.map((agent) => (
                        <DropdownMenuRadioItem key={agent.key} value={agent.key} asChild>
                            <ButtonPrimitive menuItem className="gap-1.5">
                                <AgentLogo agent={agent} />
                                <span className="truncate flex-1">{agent.name}</span>
                                <DropdownMenuItemIndicator intent="radio" />
                            </ButtonPrimitive>
                        </DropdownMenuRadioItem>
                    ))}
                    <DropdownMenuSeparator />
                    <DropdownMenuRadioItem value={CLIPBOARD_KEY} asChild>
                        <ButtonPrimitive menuItem className="gap-1.5">
                            <IconCopy className="shrink-0" />
                            <span className="truncate flex-1">Copy to clipboard</span>
                            <DropdownMenuItemIndicator intent="radio" />
                        </ButtonPrimitive>
                    </DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
