import { useActions } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconCopy, IconLogomark, IconSparkles } from '@posthog/icons'

import { useLocalStorage } from 'lib/hooks/useLocalStorage'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
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
import {
    Button as QuillButton,
    ButtonGroup as QuillButtonGroup,
    ButtonGroupSeparator as QuillButtonGroupSeparator,
    type ButtonProps as QuillButtonProps,
} from 'lib/ui/quill'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { AgentLogo, claudeLogo, cursorLogo, openaiLogo } from './AgentLogo'

export interface AgentPromptAction {
    /** Stable key used for localStorage persistence */
    key: string
    label: string
    icon?: React.ReactElement
    /** Returns the prompt text for this action */
    buildPrompt: () => string
}

/** Quill button sizes, minus the icon-only variants (the dropdown trigger derives those automatically). */
type AgentPromptButtonSize = Exclude<NonNullable<QuillButtonProps['size']>, 'icon' | 'icon-xs' | 'icon-sm' | 'icon-lg'>

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
    /** Content selected when nothing is stored yet. Falls back to the first action. */
    defaultActionKey?: string
    /** Destination selected when nothing is stored yet. Falls back to the first agent. */
    defaultAgentKey?: string
    size?: AgentPromptButtonSize
    variant?: NonNullable<QuillButtonProps['variant']>
    /** Renders the dropdown open on first paint. Useful for visual regression snapshots. */
    defaultOpen?: boolean
    /** Fired whenever a combo runs (agent deeplink opened or clipboard copied). Useful for analytics. */
    onRun?: (params: { actionKey: string; agentKey: string }) => void
    /** GitHub `owner/repo` slug passed to agents that can open a specific repository (e.g. Claude Code). */
    repository?: string
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
    /** Verb shown on the main button when this provider is selected. */
    verb: string
    /** Opens the prompt in this agent. Some agents double-encode or truncate prompts due to URL length limits. */
    open: (prompt: string, context: AgentOpenContext) => void
}

interface AgentOpenContext {
    askSidePanelMax: (prompt: string) => void
    actionLabel: string
    repository?: string
}

/** Max prompt chars before truncation for agents that have strict URL length limits. */
const LIMIT_LONG = 8_000
const LIMIT_CLAUDE = 5_000
const LIMIT_SHORT = 4_000

function withLimit(prompt: string, maxChars: number, build: (p: string) => string): string {
    return build(prompt.slice(0, maxChars))
}

function openDeepLink(buildDeepLink: (prompt: string) => string): (prompt: string) => void {
    return (prompt: string) => window.open(buildDeepLink(prompt), '_blank')
}

const AGENTS: AgentDef[] = [
    {
        key: 'posthog-ai',
        name: 'PostHog AI',
        logo: <IconSparkles className="size-4 shrink-0 text-ai" />,
        verb: 'Open',
        open: (prompt, { askSidePanelMax }) => askSidePanelMax(prompt),
    },
    {
        key: 'posthog-code',
        name: 'PostHog Code',
        logo: <IconLogomark className="size-4 shrink-0" />,
        verb: 'Open',
        open: openDeepLink((p) => `posthog-code://new?prompt=${encodeURIComponent(p)}`),
    },
    {
        key: 'claude-code',
        name: 'Claude Code',
        logo: claudeLogo,
        verb: 'Open',
        open: (prompt, { repository }) => {
            const query = withLimit(prompt, LIMIT_CLAUDE, (t) => encodeURIComponent(t))
            const repoParam = repository ? `repo=${encodeURIComponent(repository)}&` : ''
            window.open(`claude-cli://open?${repoParam}q=${query}`, '_blank')
        },
    },
    {
        key: 'cursor',
        name: 'Cursor',
        logo: cursorLogo,
        // Cursor wordmark is solid black; invert in dark mode so it stays visible
        logoClassName: 'dark:invert',
        verb: 'Open',
        open: openDeepLink((p) =>
            // Cursor decodes the full deeplink before parsing query params, so reserved chars need an extra escape layer.
            withLimit(
                p,
                LIMIT_LONG,
                (t) => `cursor://anysphere.cursor-deeplink/prompt?text=${encodeURIComponent(encodeURIComponent(t))}`
            )
        ),
    },
    {
        key: 'codex',
        name: 'Codex',
        logo: openaiLogo,
        verb: 'Open',
        open: openDeepLink((p) => withLimit(p, LIMIT_SHORT, (t) => `codex://new?prompt=${encodeURIComponent(t)}`)),
    },
    {
        key: 'clipboard',
        name: 'Clipboard',
        logo: <IconCopy className="size-4 shrink-0" />,
        verb: 'Copy',
        open: (prompt, { actionLabel }) => {
            void copyToClipboard(prompt, actionLabel.toLowerCase())
        },
    },
]

export function AgentPromptButton({
    actions,
    storageKey,
    defaultActionKey,
    defaultAgentKey,
    size = 'default',
    variant = 'default',
    defaultOpen = false,
    onRun,
    repository,
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
    const { askSidePanelMax } = useActions(maxGlobalLogic)

    if (actions.length === 0) {
        return null
    }

    const activeAction =
        (remembered ? actions.find((a) => a.key === remembered.actionKey) : null) ??
        actions.find((a) => a.key === defaultActionKey) ??
        actions[0]
    const activeAgent =
        (remembered?.agentKey ? AGENTS.find((a) => a.key === remembered.agentKey) : null) ??
        AGENTS.find((a) => a.key === defaultAgentKey) ??
        AGENTS[0]
    const buttonLabel = `${activeAgent.verb} ${activeAction.label}`

    const selectAction = (actionKey: string): void => {
        setRemembered({ actionKey, agentKey: remembered?.agentKey ?? null })
    }

    const runCombo = (actionKey: string, agentKey: string): void => {
        const action = actions.find((a) => a.key === actionKey) ?? actions[0]
        const prompt = action.buildPrompt()
        onRun?.({ actionKey, agentKey })
        const agent = AGENTS.find((a) => a.key === agentKey)
        if (!agent) {
            return
        }
        agent.open(prompt, { askSidePanelMax, actionLabel: action.label, repository })
    }

    const selectAgent = (agentKey: string): void => {
        const actionKey = remembered?.actionKey ?? actions[0].key
        setRemembered({ actionKey, agentKey })
        setOpen(false)
    }

    const handleMainClick = (): void => {
        runCombo(activeAction.key, activeAgent.key)
    }

    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <QuillButtonGroup>
                <QuillButton
                    variant={variant}
                    size={size}
                    className="border-0"
                    onClick={handleMainClick}
                    data-attr={dataAttr}
                    title={`Run: ${buttonLabel}`}
                >
                    <AgentLogo logo={activeAgent.logo} logoClassName={activeAgent.logoClassName} />
                    <span className="truncate max-w-64">{buttonLabel}</span>
                </QuillButton>
                <QuillButtonGroupSeparator />
                <DropdownMenuTrigger asChild>
                    <QuillButton
                        variant={variant}
                        size={size === 'default' ? 'icon' : `icon-${size}`}
                        className="border-0"
                    >
                        <IconChevronDown className="size-4 text-current" />
                    </QuillButton>
                </DropdownMenuTrigger>
            </QuillButtonGroup>

            <DropdownMenuContent align="end" className="w-56">
                {actions.length > 1 && (
                    <>
                        <DropdownMenuLabel>Content</DropdownMenuLabel>
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
                <DropdownMenuLabel>Destination</DropdownMenuLabel>
                <DropdownMenuRadioGroup value={activeAgent.key} onValueChange={selectAgent}>
                    {AGENTS.map((agent) => (
                        <DropdownMenuRadioItem key={agent.key} value={agent.key} asChild>
                            <ButtonPrimitive menuItem className="gap-1.5">
                                <AgentLogo logo={agent.logo} logoClassName={agent.logoClassName} />
                                <span className="truncate flex-1">{agent.name}</span>
                                <DropdownMenuItemIndicator intent="radio" />
                            </ButtonPrimitive>
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
