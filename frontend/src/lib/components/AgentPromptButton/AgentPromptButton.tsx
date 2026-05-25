import { useState } from 'react'

import { IconCopy, IconLogomark, IconMagicWand, IconStarFilled } from '@posthog/icons'

import { useLocalStorage } from 'lib/hooks/useLocalStorage'
import { ButtonGroupPrimitive, ButtonPrimitive, type ButtonSize } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
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
     * Use a unique value per call-site so different surfaces remember independently.
     */
    storageKey?: string
    size?: ButtonSize
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
        buildDeepLink: (p) => withLimit(p, LIMIT_LONG, (t) => `claude://code/new?q=${encodeURIComponent(t)}`),
    },
    {
        key: 'cursor',
        name: 'Cursor',
        logo: cursorLogo,
        // Cursor wordmark is solid black; invert in dark mode so it stays visible
        logoClassName: 'dark:invert',
        buildDeepLink: (p) =>
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
    storageKey = 'agent-prompt-button',
    size = 'sm',
    'data-attr': dataAttr,
}: AgentPromptButtonProps): JSX.Element | null {
    const [remembered, setRemembered] = useLocalStorage<RememberedCombo | null>(`${storageKey}:combo`, null)
    const [open, setOpen] = useState(false)

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

    const selectAgent = (agentKey: string): void => {
        setRemembered({ actionKey: remembered?.actionKey ?? actions[0].key, agentKey })
        setOpen(false)
    }

    const handleMainClick = (): void => {
        if (!hasTarget) {
            setOpen(true)
            return
        }
        const prompt = activeAction.buildPrompt()
        if (isClipboard) {
            void copyToClipboard(prompt, `${activeAction.label.toLowerCase()} prompt`)
        } else if (activeAgent) {
            invokeAgent(activeAgent, prompt)
        }
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

            <DropdownMenuContent align="end" className="w-52">
                {actions.length > 1 && (
                    <>
                        <DropdownMenuGroup>
                            {actions.map((action) => (
                                <DropdownMenuItem key={action.key} asChild onSelect={(e) => e.preventDefault()}>
                                    <ButtonPrimitive
                                        menuItem
                                        active={activeAction.key === action.key}
                                        onClick={() => selectAction(action.key)}
                                        className="gap-1.5"
                                    >
                                        {action.icon}
                                        {action.label}
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuGroup>
                        <DropdownMenuSeparator />
                    </>
                )}
                <DropdownMenuGroup>
                    {AGENTS.map((agent) => (
                        <DropdownMenuItem key={agent.key} asChild onSelect={() => selectAgent(agent.key)}>
                            <ButtonPrimitive menuItem active={remembered?.agentKey === agent.key} className="gap-1.5">
                                <AgentLogo agent={agent} />
                                <span className="truncate flex-1">{agent.name}</span>
                                {remembered?.agentKey === agent.key && (
                                    <IconStarFilled className="shrink-0 text-warning size-3" />
                                )}
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    <DropdownMenuItem asChild onSelect={() => selectAgent(CLIPBOARD_KEY)}>
                        <ButtonPrimitive menuItem active={isClipboard} className="gap-1.5">
                            <IconCopy className="shrink-0" />
                            <span className="truncate flex-1">Copy to clipboard</span>
                            {isClipboard && <IconStarFilled className="shrink-0 text-warning size-3" />}
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
