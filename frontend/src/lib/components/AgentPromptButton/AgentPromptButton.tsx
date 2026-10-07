import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useState } from 'react'

import { IconCheckbox, IconChevronDown, IconCopy, IconLogomark, IconSparkles } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useLocalStorage } from 'lib/hooks/useLocalStorage'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
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
import { cn } from 'lib/utils/css-classes'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { AgentLogo, claudeLogo, cursorLogo, openaiLogo } from './AgentLogo'

export interface AgentPromptAction {
    /** Stable key used for localStorage persistence */
    key: string
    label: string
    icon?: React.ReactElement
    /** Returns the prompt text for this action */
    buildPrompt: () => string
}

export type AgentPromptDestination =
    | 'posthog-ai'
    | 'posthog-code'
    | 'posthog-task'
    | 'claude-code'
    | 'claude-desktop'
    | 'claude-code-vscode'
    | 'claude-code-web'
    | 'cursor'
    | 'codex'
    | 'clipboard'

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
    defaultAgentKey?: AgentPromptDestination
    agentKeys?: AgentPromptDestination[]
    agentSelectionMode?: 'select' | 'run'
    /** `destination` names the agent on the main button ("Open in Cursor") instead of the prompt ("Open Fix prompt"). */
    labelMode?: 'action' | 'destination'
    /** Extra classes for the dropdown menu, e.g. a higher z-index when the button sits inside a toast. */
    menuClassName?: string
    onOpenChange?: (open: boolean) => void
    size?: AgentPromptButtonSize
    variant?: NonNullable<QuillButtonProps['variant']>
    /** Renders the dropdown open on first paint. Useful for visual regression snapshots. */
    defaultOpen?: boolean
    /** Fired whenever a combo runs (agent deeplink opened or clipboard copied). Useful for analytics. */
    onRun?: (params: { actionKey: string; agentKey: string }) => void
    /** GitHub `owner/repo` slug passed to agents that can open a specific repository (e.g. Claude Code, Codex). */
    repository?: string
    'data-attr'?: string
}

interface RememberedCombo {
    actionKey: string
    agentKey: string | null
}

interface AgentDef {
    key: AgentPromptDestination
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

const CLAUDE_CODE_CLI_MAX_PROMPT_CHARS = 5_000
const CLAUDE_DESKTOP_MAX_PROMPT_CHARS = 14_000
/** Cap for apps that document no limit, sized to stay well inside OS URL handler limits. */
const UNDOCUMENTED_MAX_PROMPT_CHARS = 4_000

const CURSOR_MAX_URL_LENGTH = 10_000
/** Many web servers reject request lines over about 8 KB with a 414, so the claude.ai link stays under that. */
const CLAUDE_CODE_WEB_MAX_URL_LENGTH = 8_000

function truncatePrompt(prompt: string, maxChars: number): string {
    if (prompt.length <= maxChars) {
        return prompt
    }
    // A cut between the two halves of a surrogate pair (an emoji, for example) leaves a lone
    // surrogate, and encodeURIComponent throws a URIError on it.
    const lastCode = prompt.charCodeAt(maxChars - 1)
    const end = lastCode >= 0xd800 && lastCode <= 0xdbff ? maxChars - 1 : maxChars
    return prompt.slice(0, end)
}

function buildWithinUrlLength(prompt: string, maxUrlLength: number, build: (prompt: string) => string): string {
    const full = build(prompt)
    if (full.length <= maxUrlLength) {
        return full
    }
    let low = 0
    let high = prompt.length
    while (low < high) {
        const mid = Math.ceil((low + high) / 2)
        if (build(truncatePrompt(prompt, mid)).length <= maxUrlLength) {
            low = mid
        } else {
            high = mid - 1
        }
    }
    return build(truncatePrompt(prompt, low))
}

function openDeepLink(buildDeepLink: (prompt: string, repository?: string) => string): AgentDef['open'] {
    return (prompt, { repository }) => window.open(buildDeepLink(prompt, repository), '_blank')
}

export function buildPostHogCodeDeepLink(prompt: string, repository?: string): string {
    const repoParam = repository ? `&repo=${encodeURIComponent(repository)}` : ''
    return `posthog-code://new?prompt=${encodeURIComponent(prompt)}${repoParam}`
}

export function buildPostHogTaskUrl(prompt: string): string {
    return combineUrl(urls.taskNew(), { ask: prompt }).url
}

export function buildClaudeCodeDeepLink(prompt: string, repository?: string): string {
    const query = encodeURIComponent(truncatePrompt(prompt, CLAUDE_CODE_CLI_MAX_PROMPT_CHARS))
    const repoParam = repository ? `repo=${encodeURIComponent(repository)}&` : ''
    return `claude-cli://open?${repoParam}q=${query}`
}

/** The Desktop link takes only an absolute folder path, so it cannot select the repository. */
export function buildClaudeDesktopDeepLink(prompt: string): string {
    return `claude://code/new?q=${encodeURIComponent(truncatePrompt(prompt, CLAUDE_DESKTOP_MAX_PROMPT_CHARS))}`
}

export function buildClaudeCodeVSCodeDeepLink(prompt: string): string {
    return `vscode://anthropic.claude-code/open?prompt=${encodeURIComponent(truncatePrompt(prompt, UNDOCUMENTED_MAX_PROMPT_CHARS))}`
}

export function buildClaudeCodeWebLink(prompt: string, repository?: string): string {
    const repoParam = repository ? `&repositories=${encodeURIComponent(repository)}` : ''
    return buildWithinUrlLength(
        prompt,
        CLAUDE_CODE_WEB_MAX_URL_LENGTH,
        (text) => `https://claude.ai/code?prompt=${encodeURIComponent(text)}${repoParam}`
    )
}

export function buildCursorDeepLink(prompt: string): string {
    // Cursor decodes the full deeplink before parsing query params, so reserved chars need an extra escape layer.
    return buildWithinUrlLength(
        prompt,
        CURSOR_MAX_URL_LENGTH,
        (text) => `cursor://anysphere.cursor-deeplink/prompt?text=${encodeURIComponent(encodeURIComponent(text))}`
    )
}

export function buildCodexDeepLink(prompt: string, repository?: string): string {
    const originParam = repository ? `&originUrl=${encodeURIComponent(`https://github.com/${repository}`)}` : ''
    return `codex://new?prompt=${encodeURIComponent(truncatePrompt(prompt, UNDOCUMENTED_MAX_PROMPT_CHARS))}${originParam}`
}

// pinned: each `key` is stored in localStorage and sent as the `agent` analytics property, so renaming one resets
// remembered choices and splits the analytics. Change `name` instead.
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
        name: 'PostHog Desktop',
        logo: <IconLogomark className="size-4 shrink-0" />,
        verb: 'Open',
        open: openDeepLink(buildPostHogCodeDeepLink),
    },
    {
        key: 'posthog-task',
        name: 'New task',
        logo: <IconCheckbox className="size-4 shrink-0" />,
        verb: 'Open',
        open: (prompt) => newInternalTab(buildPostHogTaskUrl(prompt)),
    },
    {
        key: 'claude-code',
        name: 'Claude Code CLI',
        logo: claudeLogo,
        verb: 'Open',
        open: openDeepLink(buildClaudeCodeDeepLink),
    },
    {
        key: 'claude-desktop',
        name: 'Claude Desktop',
        logo: claudeLogo,
        verb: 'Open',
        open: openDeepLink(buildClaudeDesktopDeepLink),
    },
    {
        key: 'claude-code-vscode',
        name: 'Claude Code in VS Code',
        logo: claudeLogo,
        verb: 'Open',
        open: openDeepLink(buildClaudeCodeVSCodeDeepLink),
    },
    {
        key: 'claude-code-web',
        name: 'Claude Code on the web',
        logo: claudeLogo,
        verb: 'Open',
        open: (prompt, { repository }) =>
            window.open(buildClaudeCodeWebLink(prompt, repository), '_blank', 'noopener,noreferrer'),
    },
    {
        key: 'cursor',
        name: 'Cursor',
        logo: cursorLogo,
        // Cursor wordmark is solid black; invert in dark mode so it stays visible
        logoClassName: 'dark:invert',
        verb: 'Open',
        open: openDeepLink(buildCursorDeepLink),
    },
    {
        key: 'codex',
        name: 'Codex',
        logo: openaiLogo,
        verb: 'Open',
        open: openDeepLink(buildCodexDeepLink),
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
    agentKeys,
    agentSelectionMode = 'select',
    labelMode = 'action',
    menuClassName,
    onOpenChange,
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
    const { todayRailEnabled } = useValues(todayShellLogic)
    const showDesktopEntryPoints = useFeatureFlag('POSTHOG_DESKTOP_ENTRY_POINTS')
    const availableAgents = AGENTS.filter((agent) => {
        if (agent.key === 'posthog-task') {
            return (
                !showDesktopEntryPoints &&
                (!agentKeys || agentKeys.includes('posthog-task') || agentKeys.includes('posthog-code'))
            )
        }
        return (
            (!agentKeys || agentKeys.includes(agent.key)) &&
            !(todayRailEnabled && agent.key === 'posthog-ai') &&
            !(!showDesktopEntryPoints && agent.key === 'posthog-code')
        )
    })

    if (actions.length === 0 || availableAgents.length === 0) {
        return null
    }

    const activeAction =
        (remembered ? actions.find((a) => a.key === remembered.actionKey) : null) ??
        actions.find((a) => a.key === defaultActionKey) ??
        actions[0]
    const defaultAgent = availableAgents.find((a) => a.key === defaultAgentKey) ?? availableAgents[0]
    const activeAgent =
        agentSelectionMode === 'run'
            ? defaultAgent
            : ((remembered?.agentKey ? availableAgents.find((a) => a.key === remembered.agentKey) : null) ??
              defaultAgent)
    const buttonLabel =
        labelMode === 'destination' && activeAgent.key !== 'clipboard'
            ? `Open in ${activeAgent.name}`
            : `${activeAgent.verb} ${activeAction.label}`

    const selectAction = (actionKey: string): void => {
        setRemembered({ actionKey, agentKey: remembered?.agentKey ?? null })
    }

    const runCombo = (actionKey: string, agentKey: string): void => {
        const action = actions.find((a) => a.key === actionKey) ?? actions[0]
        const prompt = action.buildPrompt()
        onRun?.({ actionKey, agentKey })
        const agent = availableAgents.find((a) => a.key === agentKey)
        if (!agent) {
            return
        }
        agent.open(prompt, { askSidePanelMax, actionLabel: action.label, repository })
    }

    const selectAgent = (agentKey: string): void => {
        const actionKey = remembered?.actionKey ?? actions[0].key
        if (agentSelectionMode === 'run') {
            runCombo(actionKey, agentKey)
            setOpen(false)
            return
        }
        setRemembered({ actionKey, agentKey })
        setOpen(false)
    }

    const handleMainClick = (): void => {
        runCombo(activeAction.key, activeAgent.key)
    }

    return (
        <DropdownMenu
            open={open}
            onOpenChange={(nextOpen) => {
                setOpen(nextOpen)
                onOpenChange?.(nextOpen)
            }}
        >
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
                        aria-label={
                            agentSelectionMode === 'run' ? 'Open prompt in an agent' : 'Choose prompt and destination'
                        }
                    >
                        <IconChevronDown className="size-4 text-current" />
                    </QuillButton>
                </DropdownMenuTrigger>
            </QuillButtonGroup>

            <DropdownMenuContent align="end" className={cn('w-60 max-w-none', menuClassName)}>
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
                <DropdownMenuLabel>{agentSelectionMode === 'run' ? 'Open in' : 'Destination'}</DropdownMenuLabel>
                {agentSelectionMode === 'run' ? (
                    <DropdownMenuGroup>
                        {availableAgents
                            .filter((agent) => agent.key !== activeAgent.key)
                            .map((agent) => (
                                <DropdownMenuItem key={agent.key} asChild onSelect={() => selectAgent(agent.key)}>
                                    <ButtonPrimitive menuItem className="gap-1.5">
                                        <AgentLogo logo={agent.logo} logoClassName={agent.logoClassName} />
                                        <span className="truncate flex-1">{agent.name}</span>
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                            ))}
                    </DropdownMenuGroup>
                ) : (
                    <DropdownMenuRadioGroup value={activeAgent.key} onValueChange={selectAgent}>
                        {availableAgents.map((agent) => (
                            <DropdownMenuRadioItem key={agent.key} value={agent.key} asChild>
                                <ButtonPrimitive menuItem className="gap-1.5">
                                    <AgentLogo logo={agent.logo} logoClassName={agent.logoClassName} />
                                    <span className="truncate flex-1">{agent.name}</span>
                                    <DropdownMenuItemIndicator intent="radio" />
                                </ButtonPrimitive>
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
