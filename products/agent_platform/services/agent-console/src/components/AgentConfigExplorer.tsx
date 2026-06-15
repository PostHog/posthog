/**
 * `<AgentConfigExplorer />` — EXPERIMENTAL alternative to the
 * `RevisionsBrowser` config view.
 *
 * The whole revision is one filesystem. There is no separate "bundle" —
 * the files the runner reads are folded into the config they belong to:
 * the system prompt is `Instructions`, a skill's `SKILL.md` body renders
 * under the skill, a custom tool's `source.ts` renders under the tool.
 *
 * Left tree (on the shared `<FileExplorer>`):
 *   Model · Instructions · Triggers/ · Tools/ · Skills/ · MCPs/ ·
 *   Integrations/ · Secrets/
 * Model folds in the per-session limits; each trigger folds in its own auth
 * modes + a "how to use" example. Section folders (Tools, Skills, …) are
 * selectable — their detail is a high-level explainer (how native vs custom vs
 * client tools differ, how skills load). Item leaves show a meta card + the
 * actual content below.
 *
 * Right-side row affordances: an approval lock on gated tools, and a
 * "needs attention" warning on secrets / MCPs / triggers whose required
 * secret isn't set yet — the latter opens an inline set-secret popover in
 * the detail pane.
 *
 * Storybook-first (`AgentConfigExplorer.stories.tsx`). The agent overview
 * + revision dropdown stay in the host scene; this is just the body.
 */

'use client'

import {
    AlertTriangleIcon,
    CalendarClockIcon,
    CheckIcon,
    CodeIcon,
    CopyIcon,
    GlobeIcon,
    HashIcon,
    InfoIcon,
    KeyIcon,
    LinkIcon,
    LockIcon,
    MessageSquareIcon,
    PuzzleIcon,
    ScrollTextIcon,
    ServerIcon,
    SparklesIcon,
    UserIcon,
    WebhookIcon,
    WrenchIcon,
    ZapIcon,
} from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'

import type { BundleFile } from '@posthog/agent-chat/fixtures'

import { getTriggerRequiredSecrets } from '@/lib/triggerSecrets'

import { BundleFileBody } from './BundleTree'
import { EditWithAIButton } from './EditWithAIButton'
import { FileExplorer, type FileTreeNode } from './FileExplorer'

/* ── Spec subset types ──────────────────────────────────────────── */

type ToolKind = 'native' | 'client' | 'custom' | 'custom_template'
interface ToolRef {
    kind: ToolKind | string
    id: string
    path?: string
    from_template?: string
    description?: string
    requires_approval?: boolean
}
interface SkillRef {
    id: string
    path: string
    description?: string
    /** Registry lineage when pinned from a template; absent = bundle-authored. */
    from_template?: string
}
interface Trigger {
    type: string
    config?: Record<string, unknown>
    /** Per-trigger auth modes. Present on declarative triggers (webhook / chat /
     *  mcp); absent on intrinsic ones (slack / cron), which gate via their own
     *  protocol. A `public` mode means the trigger accepts anonymous callers. */
    auth?: { modes?: Array<{ type?: string }> }
}
interface McpToolEntry {
    name: string
    requires_approval?: boolean
}
interface McpRef {
    id: string
    url: string
    secrets?: string[]
    tools?: Array<string | McpToolEntry>
}
interface Limits {
    max_turns?: number
    max_tool_calls?: number
    max_wall_seconds?: number
}

// Secret keys grouped by the trigger type that requires them, derived from
// the shared trigger-secrets registry (`getTriggerRequiredSecrets`) so a
// trigger missing a key — and the Secrets section — stay in lockstep with
// the platform. `via` records which trigger contributed a secret.
function requiredSecretsByTrigger(spec: Record<string, unknown>): Record<string, string[]> {
    const out: Record<string, string[]> = {}
    for (const req of getTriggerRequiredSecrets(spec)) {
        ;(out[req.trigger] ??= []).push(req.key)
    }
    return out
}

export interface AgentConfigExplorerProps {
    /** The revision's `spec` JSON (model, triggers, tools, skills, …). */
    spec: Record<string, unknown>
    /** The revision's bundle files (agent.md, skills/<id>/SKILL.md, tools/…). */
    files: BundleFile[]
    /**
     * Secret keys that are currently SET on the agent. When provided, any
     * required key not in this list is flagged as "needs attention". When
     * omitted, no secret warnings are shown.
     */
    setSecrets?: string[]
    /**
     * Open the secret editor for `key` (the host mounts the real
     * `<SecretEditDialog>`, driven by `?edit_secret=`). Covers set / rotate
     * / clear. When omitted, secret rows are read-only.
     */
    onEditSecret?: (key: string) => void
    /** Start the "add a secret the spec doesn't declare" flow (host-owned). */
    onAddCustomSecret?: () => void
    /**
     * Slack app-manifest setup, rendered under a `slack` trigger's detail.
     * The host fills this with the live `<SlackSetupCard>`; omitted in
     * Storybook / when there's no slack trigger.
     */
    slackSetup?: ReactNode
    /** Controlled selection (a node path). Falls back to `cfg:model`. */
    selectedPath?: string | null
    onSelectPath?: (path: string) => void
    /** Slug — threads "Edit with AI" into the bundle file viewer when set. */
    agentSlug?: string
    /** Mode-aware ingress base URL (`agent.ingress_base_url`) for the per-trigger
     *  "how to use" examples. Falls back to a placeholder host when absent. */
    ingressBaseUrl?: string
    /**
     * Outer height (passed through to `<FileExplorer>`). Pass `'100%'` to
     * fill a flex parent; defaults to the explorer's own viewport-based
     * height for standalone use.
     */
    height?: string
}

const CFG = 'cfg:'
const LEAF = 'h-3.5 w-3.5 shrink-0'

export function AgentConfigExplorer({
    spec,
    files,
    setSecrets,
    onEditSecret,
    onAddCustomSecret,
    slackSetup,
    selectedPath,
    onSelectPath,
    agentSlug,
    ingressBaseUrl,
    height,
}: AgentConfigExplorerProps): React.ReactElement {
    const [internal, setInternal] = useState<string>(`${CFG}model`)
    const selected = selectedPath ?? internal
    const select = (path: string): void => {
        setInternal(path)
        onSelectPath?.(path)
    }

    const isMissing = useMemo(() => {
        return (key: string): boolean => setSecrets !== undefined && !setSecrets.includes(key)
    }, [setSecrets])

    const tree = useMemo(() => buildTree(spec, isMissing), [spec, isMissing])

    return (
        <FileExplorer
            storageKey="file-explorer:agent-config"
            tree={tree}
            selectedPath={selected}
            onSelectPath={select}
            emptyMessage="This revision has no configuration yet."
            height={height}
        >
            <DetailPane
                spec={spec}
                files={files}
                selected={selected}
                agentSlug={agentSlug}
                ingressBaseUrl={ingressBaseUrl}
                isMissing={isMissing}
                setSecrets={setSecrets}
                onEditSecret={onEditSecret}
                onAddCustomSecret={onAddCustomSecret}
                slackSetup={slackSetup}
                onSelectPath={select}
            />
        </FileExplorer>
    )
}

/* ── Tree builder ───────────────────────────────────────────────── */

const tools = (s: Record<string, unknown>): ToolRef[] => (Array.isArray(s.tools) ? (s.tools as ToolRef[]) : [])
const skills = (s: Record<string, unknown>): SkillRef[] => (Array.isArray(s.skills) ? (s.skills as SkillRef[]) : [])
const triggers = (s: Record<string, unknown>): Trigger[] => (Array.isArray(s.triggers) ? (s.triggers as Trigger[]) : [])
const mcps = (s: Record<string, unknown>): McpRef[] => (Array.isArray(s.mcps) ? (s.mcps as McpRef[]) : [])
const secrets = (s: Record<string, unknown>): string[] => (Array.isArray(s.secrets) ? (s.secrets as string[]) : [])

function stripNamespace(id: string): string {
    const slash = id.indexOf('/')
    return slash === -1 ? id : id.slice(slash + 1)
}

function warnBadge(title: string): ReactNode {
    return (
        <span title={title}>
            <AlertTriangleIcon className="h-3.5 w-3.5 text-amber-500" />
        </span>
    )
}
function lockBadge(): ReactNode {
    return (
        <span title="Calls to this tool require human approval before they run.">
            <LockIcon className="h-3 w-3 text-amber-500" />
        </span>
    )
}
function customPill(): ReactNode {
    return (
        <span
            title="Authored in this agent's bundle."
            className="rounded bg-violet-500/15 px-1 py-px text-[0.5625rem] font-medium uppercase tracking-wide text-violet-700 dark:text-violet-300"
        >
            custom
        </span>
    )
}
/** Whether a trigger accepts anonymous callers. Declarative triggers
 *  (webhook / chat / mcp) are public iff their auth modes include `public`;
 *  intrinsic triggers (slack / cron) are never anonymous. */
function isTriggerPublic(t: Trigger): boolean {
    const modes = Array.isArray(t.auth?.modes) ? t.auth.modes : []
    return modes.some((m) => m?.type === 'public')
}

/** Reachability pill for a trigger row — loud `public` when it accepts
 *  anonymous callers, quiet `private` otherwise, with a tooltip that names the
 *  gate. The trigger analogue of `customPill` / `lockBadge` on tools. */
function reachabilityPill(t: Trigger): ReactNode {
    if (isTriggerPublic(t)) {
        return (
            <span
                title="Publicly accessible — accepts anonymous, unauthenticated callers. Anyone who can reach the endpoint can start a session."
                className="rounded bg-amber-500/15 px-1 py-px text-[0.5625rem] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-300"
            >
                public
            </span>
        )
    }
    const title =
        t.type === 'slack'
            ? 'Private — gated by the Slack request signature.'
            : t.type === 'cron'
              ? 'Private — fires from the internal scheduler; not externally reachable.'
              : 'Private — callers must authenticate (PostHog token / bearer).'
    return (
        <span
            title={title}
            className="rounded bg-emerald-500/15 px-1 py-px text-[0.5625rem] font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-300"
        >
            private
        </span>
    )
}

/** Combine 0+ trailing badges into one inline group (undefined when empty). */
function trailingBadges(nodes: ReactNode[]): ReactNode | undefined {
    const items = nodes.filter(Boolean)
    if (items.length === 0) {
        return undefined
    }
    return (
        <span className="flex items-center gap-1">
            {items.map((n, i) => (
                <span key={i}>{n}</span>
            ))}
        </span>
    )
}

const integrations = (s: Record<string, unknown>): string[] =>
    Array.isArray(s.integrations) ? (s.integrations as string[]) : []

interface SecretEntry {
    key: string
    /** Trigger type that requires this key (e.g. "slack"), if any. */
    via?: string
}

/**
 * Every secret the agent reads: the spec's top-level `secrets[]` plus any
 * keys triggers require (e.g. Slack's signing secret), declared-first and
 * deduped. The agent reads both the same way, so the Secrets section lists
 * both — annotated with the trigger that contributed it.
 */
function allSecretKeys(spec: Record<string, unknown>): SecretEntry[] {
    const out: SecretEntry[] = []
    const seen = new Set<string>()
    for (const key of secrets(spec)) {
        if (!seen.has(key)) {
            seen.add(key)
            out.push({ key })
        }
    }
    for (const req of getTriggerRequiredSecrets(spec)) {
        if (!seen.has(req.key)) {
            seen.add(req.key)
            out.push({ key: req.key, via: req.trigger })
        }
    }
    return out
}

function buildTree(spec: Record<string, unknown>, isMissing: (k: string) => boolean): FileTreeNode {
    const children: FileTreeNode[] = [
        { type: 'file', name: 'model', path: `${CFG}model`, icon: <SparklesIcon className={LEAF} /> },
        { type: 'file', name: 'instructions', path: `${CFG}instructions`, icon: <ScrollTextIcon className={LEAF} /> },
    ]

    const reqByTrigger = requiredSecretsByTrigger(spec)
    const trg = triggers(spec)
    if (trg.length) {
        children.push({
            type: 'folder',
            name: 'triggers',
            path: `${CFG}triggers`,
            icon: <ZapIcon className={LEAF} />,
            children: trg.map((t, i) => {
                const missing = (reqByTrigger[t.type] ?? []).filter(isMissing)
                return {
                    type: 'file',
                    name: t.type,
                    path: `${CFG}trigger/${i}`,
                    icon: <TriggerIcon type={t.type} />,
                    trailing: trailingBadges([
                        reachabilityPill(t),
                        missing.length ? warnBadge(`Needs secret(s): ${missing.join(', ')}`) : null,
                    ]),
                }
            }),
        })
    }

    const tls = tools(spec)
    if (tls.length) {
        children.push({
            type: 'folder',
            name: 'tools',
            path: `${CFG}tools`,
            icon: <WrenchIcon className={LEAF} />,
            children: tls.map((t) => {
                const isCustom = t.kind === 'custom' || t.kind === 'custom_template'
                return {
                    type: 'file',
                    name: stripNamespace(t.id),
                    path: `${CFG}tool/${t.id}`,
                    icon: <ToolKindIcon kind={t.kind} />,
                    trailing: trailingBadges([
                        isCustom ? customPill() : null,
                        t.requires_approval ? lockBadge() : null,
                    ]),
                }
            }),
        })
    }

    const sks = skills(spec)
    if (sks.length) {
        children.push({
            type: 'folder',
            name: 'skills',
            path: `${CFG}skills`,
            icon: <PuzzleIcon className={LEAF} />,
            children: sks.map((s) => ({
                type: 'file',
                name: s.id,
                path: `${CFG}skill/${s.id}`,
                description: s.description,
                icon: <PuzzleIcon className={LEAF} />,
                trailing: s.from_template ? undefined : customPill(),
            })),
        })
    }

    const ms = mcps(spec)
    if (ms.length) {
        children.push({
            type: 'folder',
            name: 'mcps',
            path: `${CFG}mcps`,
            icon: <ServerIcon className={LEAF} />,
            children: ms.map((m) => {
                const missing = (m.secrets ?? []).filter(isMissing)
                return {
                    type: 'file',
                    name: m.id,
                    path: `${CFG}mcp/${m.id}`,
                    icon: <ServerIcon className={LEAF} />,
                    trailing: missing.length ? warnBadge(`Needs secret(s): ${missing.join(', ')}`) : undefined,
                }
            }),
        })
    }

    const intg = integrations(spec)
    if (intg.length) {
        children.push({
            type: 'folder',
            name: 'integrations',
            path: `${CFG}integrations`,
            icon: <LinkIcon className={LEAF} />,
            children: intg.map((name) => ({
                type: 'file',
                name,
                path: `${CFG}integration/${name}`,
                icon: <LinkIcon className={LEAF} />,
            })),
        })
    }

    const scr = allSecretKeys(spec)
    if (scr.length) {
        const anyMissing = scr.some((s) => isMissing(s.key))
        children.push({
            type: 'folder',
            name: 'secrets',
            path: `${CFG}secrets`,
            icon: <KeyIcon className={LEAF} />,
            trailing: anyMissing ? warnBadge('One or more secrets are not set.') : undefined,
            children: scr.map((s) => ({
                type: 'file',
                name: s.key,
                path: `${CFG}secret/${s.key}`,
                icon: <KeyIcon className={LEAF} />,
                trailing: isMissing(s.key) ? warnBadge(`${s.key} is not set — needs attention.`) : undefined,
            })),
        })
    }

    return { type: 'folder', name: '', children }
}

/* ── Detail pane ────────────────────────────────────────────────── */

function DetailPane({
    spec,
    files,
    selected,
    agentSlug,
    ingressBaseUrl,
    isMissing,
    setSecrets,
    onEditSecret,
    onAddCustomSecret,
    slackSetup,
    onSelectPath,
}: {
    spec: Record<string, unknown>
    files: BundleFile[]
    selected: string
    agentSlug?: string
    ingressBaseUrl?: string
    isMissing: (k: string) => boolean
    setSecrets?: string[]
    onEditSecret?: (key: string) => void
    onAddCustomSecret?: () => void
    slackSetup?: ReactNode
    onSelectPath: (path: string) => void
}): React.ReactElement {
    const rest = selected.startsWith(CFG) ? selected.slice(CFG.length) : selected
    const [section, ...idParts] = rest.split('/')
    const id = idParts.join('/')
    const fileFor = (path: string): BundleFile | undefined => files.find((f) => f.path === path)
    const slug = agentSlug ?? 'this agent'

    // Every detail Card gets the same chrome — icon + title + an "Edit with
    // AI" pill + an info toggle that explains the section — via this helper.
    const card = (icon: ReactNode, title: string, body: ReactNode, editPrompt: string): React.ReactElement => (
        <Card
            icon={icon}
            title={title}
            path={selected}
            body={body}
            agentSlug={agentSlug}
            editPrompt={editPrompt}
            info={SECTION_INFO[section]}
        />
    )

    switch (section) {
        case 'model':
            return card(
                <SparklesIcon className={HEAD} />,
                'Model',
                <ModelBody spec={spec} />,
                `Help me change the model or reasoning for \`${slug}\`.`
            )
        case 'instructions': {
            const md = fileFor('agent.md')
            // Goes through `card()` like every other section so it gets the
            // info toggle + "Edit with AI"; the body is the agent.md content.
            return card(
                <ScrollTextIcon className={HEAD} />,
                'Instructions · agent.md',
                md ? (
                    <Pad>
                        <BundleFileBody file={md} />
                    </Pad>
                ) : (
                    <Pad>
                        <Muted>No agent.md in this revision.</Muted>
                    </Pad>
                ),
                `Help me write the system prompt (agent.md) for \`${slug}\`.`
            )
        }
        case 'triggers':
            return card(
                <ZapIcon className={HEAD} />,
                'Triggers',
                <TriggersOverview
                    spec={spec}
                    isMissing={isMissing}
                    onSelectPath={onSelectPath}
                    agentSlug={agentSlug}
                    ingressBaseUrl={ingressBaseUrl}
                />,
                `Help me with the triggers for \`${slug}\`.`
            )
        case 'trigger': {
            const t = triggers(spec)[Number(id)]
            const required = t ? (requiredSecretsByTrigger(spec)[t.type] ?? []) : []
            return card(
                <TriggerIcon type={t?.type} />,
                `Trigger · ${t?.type ?? id}`,
                <TriggerBody
                    trigger={t}
                    requiredKeys={required}
                    isMissing={isMissing}
                    onEditSecret={onEditSecret}
                    slackSetup={t?.type === 'slack' ? slackSetup : undefined}
                    agentSlug={agentSlug}
                    ingressBaseUrl={ingressBaseUrl}
                />,
                `Help me configure the ${t?.type ?? ''} trigger for \`${slug}\`.`
            )
        }
        case 'tools':
            return card(
                <WrenchIcon className={HEAD} />,
                'Tools',
                <ToolsOverview spec={spec} onSelectPath={onSelectPath} />,
                `Help me with the tools for \`${slug}\`.`
            )
        case 'tool': {
            const t = tools(spec).find((x) => x.id === id)
            return card(
                <ToolKindIcon kind={t?.kind} />,
                id,
                <ToolBody tool={t} sourceFile={fileFor(`tools/${id}/source.ts`)} />,
                `Help me with the \`${id}\` tool on \`${slug}\`.`
            )
        }
        case 'skills':
            return card(
                <PuzzleIcon className={HEAD} />,
                'Skills',
                <SkillsOverview spec={spec} onSelectPath={onSelectPath} />,
                `Help me with the skills for \`${slug}\`.`
            )
        case 'skill': {
            const s = skills(spec).find((x) => x.id === id)
            return card(
                <PuzzleIcon className={HEAD} />,
                `Skill · ${id}`,
                <SkillBody skill={s} bodyFile={fileFor(`skills/${id}/SKILL.md`)} />,
                `Help me edit the \`${id}\` skill on \`${slug}\`.`
            )
        }
        case 'mcps':
            return card(
                <ServerIcon className={HEAD} />,
                'MCPs',
                <McpsOverview spec={spec} isMissing={isMissing} onSelectPath={onSelectPath} />,
                `Help me with the MCP servers for \`${slug}\`.`
            )
        case 'mcp': {
            const m = mcps(spec).find((x) => x.id === id)
            return card(
                <ServerIcon className={HEAD} />,
                `MCP · ${id}`,
                <McpBody mcp={m} isMissing={isMissing} onEditSecret={onEditSecret} />,
                `Help me with the \`${id}\` MCP connection on \`${slug}\`.`
            )
        }
        case 'integrations':
            return card(
                <LinkIcon className={HEAD} />,
                'Integrations',
                <IntegrationsOverview spec={spec} onSelectPath={onSelectPath} />,
                `Help me with the integrations for \`${slug}\`.`
            )
        case 'integration':
            return card(
                <LinkIcon className={HEAD} />,
                `Integration · ${id}`,
                <IntegrationBody name={id} />,
                `Help me wire up the \`${id}\` integration for \`${slug}\`.`
            )
        case 'secrets':
            return card(
                <KeyIcon className={HEAD} />,
                'Secrets',
                <SecretsOverview
                    spec={spec}
                    setSecrets={setSecrets}
                    isMissing={isMissing}
                    onSelectPath={onSelectPath}
                    onAddCustomSecret={onAddCustomSecret}
                />,
                `Help me set up the secrets for \`${slug}\`.`
            )
        case 'secret': {
            const via = allSecretKeys(spec).find((s) => s.key === id)?.via
            return card(
                <KeyIcon className={HEAD} />,
                `Secret · ${id}`,
                <SecretBody name={id} via={via} missing={isMissing(id)} onEditSecret={onEditSecret} />,
                `Help me set the \`${id}\` secret for \`${slug}\`.`
            )
        }
        default: {
            const file = fileFor(selected)
            return file ? <BundleFileBody file={file} /> : <Empty>Pick a configuration item.</Empty>
        }
    }
}

const HEAD = 'h-4 w-4 shrink-0 text-muted-foreground'

// One-paragraph "what is this section" copy, surfaced by the header info
// toggle. Singular item paths alias to their section.
const SECTION_INFO: Record<string, string> = {
    model: 'The LLM every request goes to. `reasoning` sets the extended-thinking budget — higher for planning-heavy work, lower or omitted for simple lookups. Limits are the per-session safety caps the runner enforces; when one is hit the session ends with `max_*_reached` and the last partial output is kept.',
    instructions:
        'The system prompt (agent.md), prepended to every turn. Keep it short and let skills carry the depth.',
    triggers:
        "What can start a session: cron schedules, chat messages, webhooks, Slack mentions, or MCP transport. A `public` tag marks a trigger that accepts anonymous callers; `private` means it's authed or intrinsically gated. A ⚠ flags a trigger whose required secret isn't set.",
    tools: 'Callable functions the agent has. Native = built-in runner tools (no setup); custom = authored in this bundle and run in a sandbox; client = fulfilled by the host UI. A 🔒 marks calls that need approval first.',
    skills: 'Markdown playbooks loaded on demand via @posthog/load-skill. Only the index (id + description) sits in the prompt; a body costs tokens only when the model loads it — so the description is the signal for when to load.',
    mcps: 'Remote MCP servers the agent connects to at session start. Each exposes a curated tool list; some of those tools are approval-gated.',
    integrations:
        'Team-level integrations (e.g. slack, github) the agent expects to be configured at the project level. The agent reuses the team connection — it does not hold its own credential.',
    secrets:
        "Encrypted env values the agent reads (referenced as ${KEY} in tool args); values are never shown. A ⚠ means a required key isn't set yet.",
}
SECTION_INFO.trigger = SECTION_INFO.triggers
SECTION_INFO.tool = SECTION_INFO.tools
SECTION_INFO.skill = SECTION_INFO.skills
SECTION_INFO.mcp = SECTION_INFO.mcps
SECTION_INFO.integration = SECTION_INFO.integrations
SECTION_INFO.secret = SECTION_INFO.secrets

function Card({
    icon,
    title,
    path,
    body,
    agentSlug,
    editPrompt,
    info,
}: {
    icon: ReactNode
    title: string
    path: string
    body: ReactNode
    agentSlug?: string
    editPrompt?: string
    info?: ReactNode
}): React.ReactElement {
    const [infoOpen, setInfoOpen] = useState(false)
    return (
        <div className="flex h-full flex-col">
            <div className="flex items-center gap-2 border-b border-border bg-muted/10 px-3 py-1.5">
                {icon}
                <span className="font-mono text-[0.8125rem] text-foreground">{title}</span>
                <div className="ml-auto flex items-center gap-2">
                    {agentSlug ? (
                        <EditWithAIButton
                            prompt={editPrompt ?? `Help me edit the ${title} configuration of \`${agentSlug}\`.`}
                            agentSlug={agentSlug}
                            compact
                        />
                    ) : null}
                    {info ? (
                        <button
                            type="button"
                            onClick={() => setInfoOpen((o) => !o)}
                            aria-pressed={infoOpen}
                            aria-label={infoOpen ? 'Hide section info' : 'Show section info'}
                            className={
                                'flex h-5 w-5 items-center justify-center rounded transition-colors ' +
                                (infoOpen
                                    ? 'bg-primary text-primary-foreground shadow-sm'
                                    : 'text-muted-foreground hover:bg-muted hover:text-foreground')
                            }
                        >
                            <InfoIcon className="h-3 w-3" />
                        </button>
                    ) : null}
                    <code className="hidden text-[0.625rem] text-muted-foreground/60 sm:inline">{path}</code>
                </div>
            </div>
            {info && infoOpen ? (
                <div className="border-b border-primary/30 bg-primary/5 px-3 py-2 text-[0.8125rem] leading-relaxed text-foreground/80">
                    {info}
                </div>
            ) : null}
            <div className="min-h-0 flex-1 overflow-auto">{body}</div>
        </div>
    )
}

/* ── Section overviews (the "high-level info + explainers") ─────── */

function ExplainerRow({ tag, tone, children }: { tag: string; tone: string; children: ReactNode }): React.ReactElement {
    return (
        <div className="flex gap-2.5">
            <span
                className={`mt-0.5 inline-flex h-fit shrink-0 rounded px-1.5 py-0.5 text-[0.625rem] font-medium uppercase tracking-wide ${tone}`}
            >
                {tag}
            </span>
            <p className="text-[0.8125rem] leading-relaxed text-foreground/85">{children}</p>
        </div>
    )
}

/** A clickable row in a section overview that jumps to an item's detail.
 *  The list analogue of a left-tree leaf — same icon + trailing badges, so a
 *  section's detail mirrors its tree children and you can drill in from either
 *  place. */
function JumpRow({
    icon,
    label,
    description,
    trailing,
    onClick,
}: {
    icon: ReactNode
    label: string
    description?: string
    trailing?: ReactNode
    onClick: () => void
}): React.ReactElement {
    return (
        <button
            type="button"
            onClick={onClick}
            className="flex w-full items-center gap-2 rounded border border-border/60 bg-card px-2 py-1.5 text-left hover:bg-accent/40"
        >
            {icon}
            <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-[0.75rem] font-medium text-foreground">{label}</span>
                {description ? (
                    <span className="truncate text-[0.6875rem] text-muted-foreground">{description}</span>
                ) : null}
            </span>
            {trailing ? <span className="shrink-0">{trailing}</span> : null}
        </button>
    )
}

/** Section-overview list wrapper — a hairline-separated "in this section"
 *  header above the jump rows. */
function JumpList({ children }: { children: ReactNode }): React.ReactElement {
    return (
        <div className="space-y-1 border-t border-border/60 pt-3">
            <p className="text-[0.625rem] uppercase tracking-wide text-muted-foreground">In this section</p>
            <div className="flex flex-col gap-1">{children}</div>
        </div>
    )
}

function ToolsOverview({
    spec,
    onSelectPath,
}: {
    spec: Record<string, unknown>
    onSelectPath: (path: string) => void
}): React.ReactElement {
    const tls = tools(spec)
    const byKind = tls.reduce<Record<string, number>>((acc, t) => {
        acc[t.kind] = (acc[t.kind] ?? 0) + 1
        return acc
    }, {})
    return (
        <Pad>
            <p className="text-sm text-foreground/90">
                The callable functions this agent has. They differ by where they run and what they need:
            </p>
            <div className="space-y-2.5">
                <ExplainerRow tag="Built-in" tone="bg-sky-500/15 text-sky-700 dark:text-sky-300">
                    <b>Native</b> tools ship with the runner (`@posthog/*`). No setup, no code in the bundle — every
                    agent can call them.
                </ExplainerRow>
                <ExplainerRow tag="Custom" tone="bg-violet-500/15 text-violet-700 dark:text-violet-300">
                    Authored in this agent's bundle (`tools/&lt;id&gt;/source.ts`), compiled at freeze, and run in a
                    per-session sandbox. Open one to read its source.
                </ExplainerRow>
                <ExplainerRow tag="Client" tone="bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">
                    Fulfilled by the host UI (e.g. this console). Only available when the user is in a client that
                    implements them; otherwise the call returns `unhandled_client_tool`.
                </ExplainerRow>
            </div>
            <p className="text-[0.6875rem] text-muted-foreground">
                A 🔒 on a tool means its calls are approval-gated. This agent:{' '}
                {Object.entries(byKind)
                    .map(([k, n]) => `${n} ${k}`)
                    .join(', ') || 'no tools'}
                .
            </p>
            {tls.length ? (
                <JumpList>
                    {tls.map((t) => {
                        const isCustom = t.kind === 'custom' || t.kind === 'custom_template'
                        return (
                            <JumpRow
                                key={t.id}
                                icon={<ToolKindIcon kind={t.kind} />}
                                label={stripNamespace(t.id)}
                                description={t.description}
                                trailing={trailingBadges([
                                    isCustom ? customPill() : null,
                                    t.requires_approval ? lockBadge() : null,
                                ])}
                                onClick={() => onSelectPath(`${CFG}tool/${t.id}`)}
                            />
                        )
                    })}
                </JumpList>
            ) : null}
        </Pad>
    )
}

function SkillsOverview({
    spec,
    onSelectPath,
}: {
    spec: Record<string, unknown>
    onSelectPath: (path: string) => void
}): React.ReactElement {
    const sks = skills(spec)
    return (
        <Pad>
            <p className="text-sm text-foreground/90">
                Markdown playbooks the agent loads on demand via `@posthog/load-skill` — {sks.length} here.
            </p>
            <div className="space-y-2.5">
                <ExplainerRow tag="Lazy" tone="bg-muted text-muted-foreground">
                    Only the skill <b>index</b> (id + description) is in the system prompt. The body costs tokens only
                    when the model decides to load it — so the description is the one signal for <i>when</i> to load it.
                </ExplainerRow>
                <ExplainerRow tag="Body" tone="bg-muted text-muted-foreground">
                    Each skill's body is `skills/&lt;id&gt;/SKILL.md` in the bundle. Open a skill to read it inline.
                </ExplainerRow>
            </div>
            {sks.length ? (
                <JumpList>
                    {sks.map((s) => (
                        <JumpRow
                            key={s.id}
                            icon={<PuzzleIcon className={LEAF} />}
                            label={s.id}
                            description={s.description}
                            trailing={s.from_template ? undefined : customPill()}
                            onClick={() => onSelectPath(`${CFG}skill/${s.id}`)}
                        />
                    ))}
                </JumpList>
            ) : null}
        </Pad>
    )
}

function TriggersOverview({
    spec,
    isMissing,
    onSelectPath,
    agentSlug,
    ingressBaseUrl,
}: {
    spec: Record<string, unknown>
    isMissing: (k: string) => boolean
    onSelectPath: (path: string) => void
    agentSlug?: string
    ingressBaseUrl?: string
}): React.ReactElement {
    const trg = triggers(spec)
    const reqByTrigger = requiredSecretsByTrigger(spec)
    return (
        <Pad>
            <p className="text-sm text-foreground/90">What can start a session — {trg.length} configured.</p>
            <Muted>
                Open a trigger to see its config. A <strong>public</strong> tag marks a trigger that accepts anonymous
                callers; <strong>private</strong> means it's authed or intrinsically gated. A ⚠ flags a trigger whose
                required secret isn't set.
            </Muted>
            {trg.length ? (
                <JumpList>
                    {trg.map((t, i) => {
                        const missing = (reqByTrigger[t.type] ?? []).filter(isMissing)
                        return (
                            <JumpRow
                                key={i}
                                icon={<TriggerIcon type={t.type} />}
                                label={t.type}
                                trailing={trailingBadges([
                                    reachabilityPill(t),
                                    missing.length ? warnBadge(`Needs secret(s): ${missing.join(', ')}`) : null,
                                ])}
                                onClick={() => onSelectPath(`${CFG}trigger/${i}`)}
                            />
                        )
                    })}
                </JumpList>
            ) : null}
            <TriggerEndpointsBlock triggers={trg} slug={agentSlug} ingressBaseUrl={ingressBaseUrl} />
        </Pad>
    )
}

/**
 * Externally-hittable routes per trigger type. Mirrors each ingress trigger
 * module's `routes` export (`services/agent-ingress/src/triggers/<type>.ts`)
 * and Django's `_TRIGGER_ROUTES`. Cron is absent — it fires from the
 * janitor's scheduler, not from an inbound request.
 */
const TRIGGER_ENDPOINTS: Record<string, Array<{ method: 'POST' | 'GET'; path: string; blurb: string }>> = {
    chat: [
        { method: 'POST', path: '/run', blurb: 'start a session' },
        { method: 'POST', path: '/send', blurb: 'send a follow-up' },
        { method: 'GET', path: '/listen', blurb: 'stream events (SSE)' },
    ],
    webhook: [{ method: 'POST', path: '/webhook', blurb: 'JSON body becomes the agent’s first message' }],
    mcp: [{ method: 'POST', path: '/mcp', blurb: 'HTTP MCP server — add to any MCP client' }],
    slack: [
        { method: 'POST', path: '/slack/events', blurb: 'Event Subscriptions request URL (set in the Slack app)' },
        { method: 'POST', path: '/slack/interactivity', blurb: 'Interactivity request URL (set in the Slack app)' },
    ],
}

/**
 * The agent's hittable endpoints, one row per route across every configured
 * trigger. URLs hang off the deployment's mode-aware ingress base
 * (domain or path routing); when no public base is known we fall back to
 * the placeholder host with a note.
 */
function TriggerEndpointsBlock({
    triggers: trg,
    slug,
    ingressBaseUrl,
}: {
    triggers: Trigger[]
    slug?: string
    ingressBaseUrl?: string
}): React.ReactElement | null {
    const withEndpoints = trg.filter((t) => TRIGGER_ENDPOINTS[t.type]?.length)
    if (!withEndpoints.length) {
        return null
    }
    const base = (ingressBaseUrl ?? `${USAGE_HOST}/agents/${slug ?? '<slug>'}`).replace(/\/$/, '')
    const hasCron = trg.some((t) => t.type === 'cron')
    return (
        <div className="space-y-1.5">
            <p className="text-[0.75rem] font-medium text-foreground">Endpoints</p>
            {!ingressBaseUrl ? (
                <Muted>No public ingress URL is configured for this deployment — placeholder host shown.</Muted>
            ) : null}
            <div className="space-y-1">
                {withEndpoints.flatMap((t) =>
                    (TRIGGER_ENDPOINTS[t.type] ?? []).map((ep) => {
                        const url = `${base}${ep.path}`
                        return (
                            <div key={`${t.type}${ep.path}`} className="flex items-center gap-2 text-[0.6875rem]">
                                <TriggerIcon type={t.type} />
                                <span className="w-8 shrink-0 font-mono text-muted-foreground">{ep.method}</span>
                                <code className="truncate font-mono text-foreground" title={url}>
                                    {url}
                                </code>
                                <CopyUrlButton text={url} />
                                <span className="hidden truncate text-muted-foreground lg:inline">{ep.blurb}</span>
                            </div>
                        )
                    })
                )}
            </div>
            {hasCron ? <Muted>Cron triggers fire on their schedule — no inbound endpoint.</Muted> : null}
        </div>
    )
}

function CopyUrlButton({ text }: { text: string }): React.ReactElement {
    const [copied, setCopied] = useState(false)
    const copy = async (): Promise<void> => {
        try {
            await navigator.clipboard.writeText(text)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
        } catch {
            // Clipboard can be blocked (insecure context / permissions) — no-op,
            // the URL stays selectable.
        }
    }
    return (
        <button
            type="button"
            onClick={copy}
            aria-label="Copy URL"
            className="inline-flex shrink-0 cursor-pointer items-center rounded border border-border bg-card p-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
            {copied ? <CheckIcon className="h-3 w-3 text-success-foreground" /> : <CopyIcon className="h-3 w-3" />}
        </button>
    )
}

function McpsOverview({
    spec,
    isMissing,
    onSelectPath,
}: {
    spec: Record<string, unknown>
    isMissing: (k: string) => boolean
    onSelectPath: (path: string) => void
}): React.ReactElement {
    const ms = mcps(spec)
    return (
        <Pad>
            <p className="text-sm text-foreground/90">Remote MCP servers the agent connects to at session start.</p>
            {ms.length ? (
                <JumpList>
                    {ms.map((m) => {
                        const missing = (m.secrets ?? []).filter(isMissing)
                        const toolCount = (m.tools ?? []).length
                        return (
                            <JumpRow
                                key={m.id}
                                icon={<ServerIcon className={LEAF} />}
                                label={m.id}
                                description={`${toolCount} tool${toolCount === 1 ? '' : 's'}`}
                                trailing={
                                    missing.length ? warnBadge(`Needs secret(s): ${missing.join(', ')}`) : undefined
                                }
                                onClick={() => onSelectPath(`${CFG}mcp/${m.id}`)}
                            />
                        )
                    })}
                </JumpList>
            ) : (
                <Muted>No MCP servers declared.</Muted>
            )}
        </Pad>
    )
}

function SecretsOverview({
    spec,
    setSecrets,
    isMissing,
    onSelectPath,
    onAddCustomSecret,
}: {
    spec: Record<string, unknown>
    setSecrets?: string[]
    isMissing: (k: string) => boolean
    onSelectPath: (path: string) => void
    onAddCustomSecret?: () => void
}): React.ReactElement {
    const declared = allSecretKeys(spec)
    const declaredKeys = new Set(declared.map((s) => s.key))
    // Keys set on the application that the spec doesn't declare — the agent
    // won't read them, so flag them as orphans (mirrors the connections view).
    const extras = (setSecrets ?? []).filter((k) => !declaredKeys.has(k)).sort()
    return (
        <Pad>
            <div className="flex items-center justify-between gap-2">
                <p className="text-sm text-foreground/90">Env keys this agent reads. Values are never shown.</p>
                {onAddCustomSecret ? (
                    <button
                        type="button"
                        onClick={onAddCustomSecret}
                        className="inline-flex shrink-0 items-center gap-1 rounded border border-border/60 bg-card px-2 py-1 text-[0.6875rem] font-medium text-muted-foreground hover:bg-accent/40 hover:text-foreground"
                    >
                        <KeyIcon className="h-3 w-3" /> Add custom
                    </button>
                ) : null}
            </div>
            <div className="flex flex-col gap-1">
                {declared.map((s) => (
                    <SecretOverviewRow key={s.key} entry={s} missing={isMissing(s.key)} onSelectPath={onSelectPath} />
                ))}
            </div>
            {extras.length ? (
                <div className="space-y-1">
                    <p className="text-[0.625rem] uppercase tracking-wide text-muted-foreground">Set but not on spec</p>
                    {extras.map((k) => (
                        <SecretOverviewRow
                            key={k}
                            entry={{ key: k }}
                            missing={false}
                            orphan
                            onSelectPath={onSelectPath}
                        />
                    ))}
                </div>
            ) : null}
        </Pad>
    )
}

function SecretOverviewRow({
    entry,
    missing,
    orphan,
    onSelectPath,
}: {
    entry: SecretEntry
    missing: boolean
    orphan?: boolean
    onSelectPath: (path: string) => void
}): React.ReactElement {
    return (
        <button
            type="button"
            onClick={() => onSelectPath(`${CFG}secret/${entry.key}`)}
            className="flex items-center gap-2 rounded border border-border/60 bg-card px-2 py-1.5 text-left hover:bg-accent/40"
        >
            <KeyIcon className="h-3.5 w-3.5 text-muted-foreground" />
            <code className="flex-1 truncate font-mono text-[0.75rem] text-foreground">{entry.key}</code>
            {entry.via ? <Chip>via {entry.via}</Chip> : null}
            {orphan ? <Chip>orphan</Chip> : null}
            {missing ? (
                <span className="inline-flex items-center gap-1 text-[0.6875rem] text-amber-600 dark:text-amber-300">
                    <AlertTriangleIcon className="h-3 w-3" /> not set
                </span>
            ) : (
                <span className="text-[0.6875rem] text-emerald-600 dark:text-emerald-300">set</span>
            )}
        </button>
    )
}

function IntegrationsOverview({
    spec,
    onSelectPath,
}: {
    spec: Record<string, unknown>
    onSelectPath: (path: string) => void
}): React.ReactElement {
    const intg = integrations(spec)
    return (
        <Pad>
            <p className="text-sm text-foreground/90">
                Team-level integrations this agent expects to be configured at the project level.
            </p>
            {intg.length ? (
                <div className="flex flex-col gap-1">
                    {intg.map((name) => (
                        <button
                            key={name}
                            type="button"
                            onClick={() => onSelectPath(`${CFG}integration/${name}`)}
                            className="flex items-center gap-2 rounded border border-border/60 bg-card px-2 py-1.5 text-left hover:bg-accent/40"
                        >
                            <LinkIcon className="h-3.5 w-3.5 text-muted-foreground" />
                            <span className="flex-1 truncate text-[0.75rem] font-medium text-foreground">{name}</span>
                        </button>
                    ))}
                </div>
            ) : (
                <Muted>No integrations declared.</Muted>
            )}
        </Pad>
    )
}

function IntegrationBody({ name }: { name: string }): React.ReactElement {
    return (
        <Pad>
            <Row label="integration">
                <Chip>{name}</Chip>
            </Row>
            <p className="text-sm text-muted-foreground">
                The agent reuses the team's <code className="font-mono">{name}</code> connection. Configure it once at
                the project level — there's no per-agent credential here.
            </p>
        </Pad>
    )
}

/* ── Item detail bodies ─────────────────────────────────────────── */

function ModelBody({ spec }: { spec: Record<string, unknown> }): React.ReactElement {
    const model = typeof spec.model === 'string' ? spec.model : undefined
    const reasoning = typeof spec.reasoning === 'string' ? spec.reasoning : undefined
    const limits = (spec.limits && typeof spec.limits === 'object' ? spec.limits : {}) as Limits
    return (
        <Pad>
            <Row label="model">{model ? <Chip>{model}</Chip> : <Muted>not set</Muted>}</Row>
            <Row label="reasoning">{reasoning ? <Chip>{reasoning}</Chip> : <Muted>default</Muted>}</Row>
            <p className="pt-1 text-[0.7rem] font-medium uppercase tracking-wide text-muted-foreground">Limits</p>
            <Row label="max turns">{stat(limits.max_turns)}</Row>
            <Row label="max tool calls">{stat(limits.max_tool_calls)}</Row>
            <Row label="max wall seconds">{stat(limits.max_wall_seconds)}</Row>
        </Pad>
    )
}

/** One-line "how this trigger works" copy, shown at the top of its detail. */
const TRIGGER_EXPLAINER: Record<string, string> = {
    webhook:
        'A POST to this agent’s webhook endpoint starts a session — the raw JSON body becomes the first message. Callers must satisfy one of the auth modes below.',
    chat: 'Interactive sessions over /run + /send (the in-app chat scene or any HTTP client). Every caller is authenticated per the auth modes below.',
    mcp: 'Exposes the agent as an MCP server; clients connect over the streamable-HTTP transport and authenticate per the auth modes below.',
    slack: 'Responds to Slack mentions and thread replies for trusted workspaces. Auth is intrinsic — every request is verified by Slack request signature, so there are no auth modes to configure.',
    cron: 'Fires on a schedule from the platform scheduler. There is no external caller, so no inbound auth applies.',
}

/** What each auth mode means, surfaced next to the mode chip. */
const AUTH_MODE_BLURB: Record<string, string> = {
    public: 'Anonymous — anyone can call. Explicitly acknowledged as public exposure.',
    posthog: 'A PostHog credential (personal API key, or OAuth in future) — end-user identity.',
    jwt: 'Signed JWT verified with a per-agent secret.',
    shared_secret: 'A shared secret sent in a named header (webhook-style).',
    posthog_internal: 'PostHog server-to-server internal token.',
}

/** Declarative triggers carry author-configurable auth modes; intrinsic ones don't. */
const DECLARATIVE_TRIGGERS = new Set(['webhook', 'chat', 'mcp'])

const USAGE_HOST = 'https://<ingress-host>'

/** An example auth header line for the trigger's most demonstrable mode, or ''
 *  (public / none). Mirrors the headers `enqueue/auth.ts` actually accepts. */
function authHeaderExample(modes: string[], trigger: Trigger): string {
    if (modes.includes('public') && modes.length === 1) {
        return ''
    }
    if (modes.includes('shared_secret')) {
        const auth = (trigger as { auth?: { modes?: Array<{ type: string; header?: string }> } }).auth
        const header = auth?.modes?.find((m) => m.type === 'shared_secret')?.header ?? 'X-Webhook-Secret'
        return `  -H '${header}: <your-secret>' \\\n`
    }
    if (modes.includes('posthog')) {
        return `  -H 'Authorization: Bearer <POSTHOG_API_KEY>' \\\n`
    }
    if (modes.includes('jwt')) {
        return `  -H 'Authorization: Bearer <SIGNED_JWT>' \\\n`
    }
    if (modes.includes('posthog_internal')) {
        return `  -H 'x-posthog-internal: <INTERNAL_SECRET>' \\\n`
    }
    return ''
}

/** Copy-pasteable "how to call this trigger" examples for webhook / chat / mcp.
 *  `ingressBaseUrl` is the deployment's mode-aware base (domain or path); when
 *  absent we fall back to a path-mode placeholder host. */
function triggerUsage(
    trigger: Trigger,
    slug: string,
    ingressBaseUrl?: string
): { title: string; code: string }[] | null {
    const base = (ingressBaseUrl ?? `${USAGE_HOST}/agents/${slug}`).replace(/\/$/, '')
    const modes = ((trigger as { auth?: { modes?: Array<{ type: string }> } }).auth?.modes ?? []).map((m) => m.type)
    const authHeader = authHeaderExample(modes, trigger)
    if (trigger.type === 'webhook') {
        return [
            {
                title: 'POST the webhook — the JSON body becomes the agent’s first message',
                code: `curl -X POST ${base}/webhook \\\n  -H 'Content-Type: application/json' \\\n${authHeader}  -d '{"event": "deploy.finished", "status": "ok"}'`,
            },
        ]
    }
    if (trigger.type === 'chat') {
        return [
            {
                title: 'Start a session',
                code: `curl -X POST ${base}/run \\\n  -H 'Content-Type: application/json' \\\n${authHeader}  -d '{"message": "Hello"}'\n# → { "session_id": "…", "state": "queued" }`,
            },
            {
                title: 'Send a follow-up, then stream events (SSE)',
                code: `curl -X POST ${base}/send \\\n  -H 'Content-Type: application/json' \\\n${authHeader}  -d '{"session_id": "<id>", "message": "more"}'\n\ncurl -N '${base}/listen?session_id=<id>'`,
            },
        ]
    }
    if (trigger.type === 'mcp') {
        const flag = authHeader ? ` \\\n  --header '${authHeader.trim().replace(/^-H '|' \\$/g, '')}'` : ''
        return [
            {
                title: 'Add as an MCP server (Claude Code)',
                code: `claude mcp add --transport http ${slug} ${base}/mcp${flag}`,
            },
            {
                title: 'Or in .mcp.json',
                code: `{\n  "mcpServers": {\n    "${slug}": { "transport": "http", "url": "${base}/mcp" }\n  }\n}`,
            },
        ]
    }
    return null
}

function CopyableCode({ code }: { code: string }): React.ReactElement {
    const [copied, setCopied] = useState(false)
    const copy = async (): Promise<void> => {
        try {
            await navigator.clipboard.writeText(code)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
        } catch {
            // Clipboard may be blocked (insecure context) — the code stays selectable.
        }
    }
    return (
        <div className="relative">
            <button
                type="button"
                onClick={copy}
                className="absolute right-1.5 top-1.5 rounded border border-border bg-card px-1.5 py-0.5 text-[0.625rem] font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
            >
                {copied ? 'Copied' : 'Copy'}
            </button>
            <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-md border border-border/60 bg-muted/20 p-2.5 pr-14 text-[0.6875rem] leading-relaxed">
                {code}
            </pre>
        </div>
    )
}

function TriggerUsage({
    trigger,
    slug,
    ingressBaseUrl,
}: {
    trigger: Trigger
    slug: string
    ingressBaseUrl?: string
}): React.ReactElement | null {
    const examples = triggerUsage(trigger, slug, ingressBaseUrl)
    if (!examples) {
        return null
    }
    return (
        <div className="space-y-3 border-t border-border p-4">
            <p className="text-[0.75rem] font-medium text-foreground">How to use</p>
            {examples.map((ex) => (
                <div key={ex.title} className="space-y-1.5">
                    <p className="text-[0.7rem] text-muted-foreground">{ex.title}</p>
                    <CopyableCode code={ex.code} />
                </div>
            ))}
        </div>
    )
}

function TriggerBody({
    trigger,
    requiredKeys,
    isMissing,
    onEditSecret,
    slackSetup,
    agentSlug,
    ingressBaseUrl,
}: {
    trigger?: Trigger
    requiredKeys: string[]
    isMissing: (k: string) => boolean
    onEditSecret?: (key: string) => void
    /** Slack app-manifest setup, rendered for a slack trigger. */
    slackSetup?: ReactNode
    agentSlug?: string
    ingressBaseUrl?: string
}): React.ReactElement {
    if (!trigger) {
        return (
            <Pad>
                <Muted>Trigger not found.</Muted>
            </Pad>
        )
    }
    const cfg = trigger.config ?? {}
    const missing = requiredKeys.filter(isMissing)
    const explainer = TRIGGER_EXPLAINER[trigger.type]
    const isDeclarative = DECLARATIVE_TRIGGERS.has(trigger.type)
    const modes = ((trigger as { auth?: { modes?: Array<{ type: string }> } }).auth?.modes ?? []).map((m) => m.type)
    const isPublic = modes.includes('public')
    return (
        <div className="flex h-full flex-col">
            <Pad>
                {explainer ? (
                    <p className="mb-3 text-[0.75rem] leading-relaxed text-muted-foreground">{explainer}</p>
                ) : null}
                <Row label="type">
                    <Chip>{trigger.type}</Chip>
                </Row>
                {Object.keys(cfg).map((k) => (
                    <Row key={k} label={k}>
                        <code className="text-[0.75rem] text-foreground">{JSON.stringify(cfg[k])}</code>
                    </Row>
                ))}
                {isDeclarative ? (
                    <Row label="auth">
                        {modes.length ? (
                            <div className="flex flex-col gap-1.5">
                                {modes.map((m) => (
                                    <span key={m} className="flex items-center gap-2">
                                        <Chip>{m}</Chip>
                                        <span className="text-[0.7rem] text-muted-foreground">
                                            {AUTH_MODE_BLURB[m]}
                                        </span>
                                    </span>
                                ))}
                            </div>
                        ) : (
                            <Muted>none — locked, no caller can reach this trigger</Muted>
                        )}
                    </Row>
                ) : (
                    <Row label="auth">
                        <span className="text-[0.7rem] text-muted-foreground">
                            Intrinsic — verified by the trigger’s own protocol, not configurable.
                        </span>
                    </Row>
                )}
                {isPublic ? (
                    <Attention>
                        This trigger is <strong>public</strong> — it accepts anonymous, unauthenticated callers.
                    </Attention>
                ) : null}
                {missing.length ? (
                    <Attention>
                        Requires secret(s) not yet set: {missing.join(', ')}.
                        <div className="mt-2 flex flex-wrap gap-2">
                            {missing.map((k) => (
                                <EditSecretButton key={k} name={k} missing onEditSecret={onEditSecret} />
                            ))}
                        </div>
                    </Attention>
                ) : null}
            </Pad>
            <TriggerUsage trigger={trigger} slug={agentSlug ?? '<slug>'} ingressBaseUrl={ingressBaseUrl} />
            {slackSetup ? <div className="border-t border-border">{slackSetup}</div> : null}
        </div>
    )
}

const TOOL_KIND_META: Record<string, { label: string; blurb: string }> = {
    native: {
        label: 'Built-in (native)',
        blurb: 'Ships with the runner. No bundle code, no setup — runs server-side.',
    },
    custom: {
        label: 'Custom (bundle)',
        blurb: 'Authored in this bundle and compiled at freeze; runs in a per-session sandbox.',
    },
    custom_template: { label: 'Custom (template)', blurb: 'Pinned to a published custom-tool template.' },
    client: {
        label: 'Client (host UI)',
        blurb: 'Fulfilled by the connecting client (e.g. this console); a no-op elsewhere.',
    },
}

function ToolBody({ tool, sourceFile }: { tool?: ToolRef; sourceFile?: BundleFile }): React.ReactElement {
    if (!tool) {
        return (
            <Pad>
                <Muted>Tool not found.</Muted>
            </Pad>
        )
    }
    const meta = TOOL_KIND_META[tool.kind] ?? { label: tool.kind, blurb: '' }
    return (
        <div className="flex h-full flex-col">
            <div className="space-y-3 p-4">
                <Row label="id">
                    <code className="text-[0.75rem] text-foreground">{tool.id}</code>
                </Row>
                <Row label="kind">
                    <Chip>{meta.label}</Chip>
                </Row>
                {meta.blurb ? (
                    <p className="text-[0.75rem] leading-relaxed text-muted-foreground">{meta.blurb}</p>
                ) : null}
                <Row label="approval">
                    {tool.requires_approval ? (
                        <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-300">
                            <LockIcon className="h-3 w-3" /> required before each call
                        </span>
                    ) : (
                        <Muted>not gated</Muted>
                    )}
                </Row>
                {tool.description ? (
                    <p className="text-sm leading-relaxed text-foreground/90">{tool.description}</p>
                ) : null}
                {tool.from_template ? (
                    <Row label="template">
                        <Chip>{tool.from_template}</Chip>
                    </Row>
                ) : null}
            </div>
            {sourceFile ? (
                <div className="min-h-0 flex-1 border-t border-border">
                    <div className="border-b border-border bg-muted/10 px-4 py-1.5 text-[0.625rem] uppercase tracking-wide text-muted-foreground">
                        source · {sourceFile.path}
                    </div>
                    <div className="overflow-auto p-4">
                        <BundleFileBody file={sourceFile} />
                    </div>
                </div>
            ) : null}
        </div>
    )
}

function SkillBody({ skill, bodyFile }: { skill?: SkillRef; bodyFile?: BundleFile }): React.ReactElement {
    if (!skill) {
        return (
            <Pad>
                <Muted>Skill not found.</Muted>
            </Pad>
        )
    }
    return (
        <div className="flex h-full flex-col">
            <div className="space-y-2 p-4">
                <Row label="id">
                    <code className="text-[0.75rem] text-foreground">{skill.id}</code>
                </Row>
                <p className="text-sm leading-relaxed text-foreground/90">
                    {skill.description || <Muted>No description.</Muted>}
                </p>
                <p className="text-[0.6875rem] text-muted-foreground">
                    The description is the only signal the model gets for when to load this skill.
                </p>
            </div>
            <div className="min-h-0 flex-1 border-t border-border">
                <div className="border-b border-border bg-muted/10 px-4 py-1.5 text-[0.625rem] uppercase tracking-wide text-muted-foreground">
                    body · {bodyFile?.path ?? `skills/${skill.id}/SKILL.md`}
                </div>
                <div className="overflow-auto p-4">
                    {bodyFile ? <BundleFileBody file={bodyFile} /> : <Muted>Body not in the loaded bundle.</Muted>}
                </div>
            </div>
        </div>
    )
}

function McpBody({
    mcp,
    isMissing,
    onEditSecret,
}: {
    mcp?: McpRef
    isMissing: (k: string) => boolean
    onEditSecret?: (key: string) => void
}): React.ReactElement {
    if (!mcp) {
        return (
            <Pad>
                <Muted>MCP not found.</Muted>
            </Pad>
        )
    }
    const toolList = (mcp.tools ?? []).map((t) => (typeof t === 'string' ? { name: t } : t))
    const missing = (mcp.secrets ?? []).filter(isMissing)
    return (
        <Pad>
            <Row label="url">
                <code className="text-[0.75rem] text-foreground">{mcp.url}</code>
            </Row>
            {missing.length ? (
                <Attention>
                    Missing secret(s): {missing.join(', ')}.
                    <div className="mt-2 flex flex-wrap gap-2">
                        {missing.map((k) => (
                            <EditSecretButton key={k} name={k} missing onEditSecret={onEditSecret} />
                        ))}
                    </div>
                </Attention>
            ) : null}
            <Row label="tools">
                <span className="text-sm">{toolList.length}</span>
            </Row>
            <div className="grid grid-cols-1 gap-1 md:grid-cols-2">
                {toolList.map((t) => (
                    <div
                        key={t.name}
                        className="flex items-center gap-1.5 rounded border border-border/60 bg-card px-2 py-1"
                    >
                        <code className="flex-1 truncate font-mono text-[0.6875rem] text-foreground">{t.name}</code>
                        {t.requires_approval ? <LockIcon className="h-3 w-3 shrink-0 text-amber-500" /> : null}
                    </div>
                ))}
            </div>
        </Pad>
    )
}

function SecretBody({
    name,
    via,
    missing,
    onEditSecret,
}: {
    name: string
    via?: string
    missing: boolean
    onEditSecret?: (key: string) => void
}): React.ReactElement {
    return (
        <Pad>
            <Row label="key">
                <code className="text-[0.75rem] text-foreground">{name}</code>
            </Row>
            {via ? (
                <Row label="required by">
                    <Chip>{via} trigger</Chip>
                </Row>
            ) : null}
            <Row label="status">
                {missing ? (
                    <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-300">
                        <AlertTriangleIcon className="h-3 w-3" /> not set
                    </span>
                ) : (
                    <span className="text-emerald-600 dark:text-emerald-300">set</span>
                )}
            </Row>
            <p className="text-sm text-muted-foreground">
                Value is never shown. {missing ? 'Set it below.' : 'Rotate or clear it below.'}
            </p>
            <EditSecretButton name={name} missing={missing} onEditSecret={onEditSecret} />
        </Pad>
    )
}

/* ── Set-secret affordance ──────────────────────────────────────── */

/**
 * A pill that hands off to the host's secret editor (`onEditSecret`). The
 * host mounts the real `<SecretEditDialog>` — the canonical set / rotate /
 * clear flow shared with the connections surface — so this component stays
 * pure (Storybook-safe) and there's one editor, one set of copy.
 */
function EditSecretButton({
    name,
    missing,
    onEditSecret,
}: {
    name: string
    missing: boolean
    onEditSecret?: (key: string) => void
}): React.ReactElement | null {
    if (!onEditSecret) {
        return null
    }
    return (
        <button
            type="button"
            onClick={() => onEditSecret(name)}
            className="inline-flex items-center gap-1 rounded border border-border/60 bg-card px-2 py-1 text-[0.75rem] text-foreground hover:bg-accent/40"
        >
            <KeyIcon className="h-3 w-3" /> {missing ? 'Set' : 'Rotate'} {name}
        </button>
    )
}

/* ── Small shared bits ──────────────────────────────────────────── */

function Pad({ children }: { children: ReactNode }): React.ReactElement {
    return <div className="space-y-3 p-4">{children}</div>
}
/**
 * The common detail "row": a rounded, subtly-tinted card with the field
 * label above its value. Used by every detail body so the model page,
 * tool page, secret page, etc. all read the same.
 */
function Row({ label, children }: { label: string; children: ReactNode }): React.ReactElement {
    return (
        <div className="flex items-start gap-3 rounded-md border border-border/40 bg-muted/30 px-3 py-2">
            <span className="w-32 shrink-0 break-words pt-0.5 text-[0.625rem] font-medium uppercase leading-tight tracking-wide text-muted-foreground">
                {label}
            </span>
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5 text-sm text-foreground">{children}</div>
        </div>
    )
}
function Chip({ children }: { children: ReactNode }): React.ReactElement {
    return (
        <span className="inline-flex items-center rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 font-mono text-[0.6875rem] text-foreground">
            {children}
        </span>
    )
}
function Attention({ children }: { children: ReactNode }): React.ReactElement {
    return (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[0.8125rem] text-amber-800 dark:text-amber-200">
            {children}
        </div>
    )
}
function Muted({ children }: { children: ReactNode }): React.ReactElement {
    return <span className="text-xs italic text-muted-foreground">{children}</span>
}
function Empty({ children }: { children: ReactNode }): React.ReactElement {
    return <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">{children}</div>
}
function stat(value?: number): ReactNode {
    return value !== undefined ? (
        <span className="font-mono text-sm text-foreground">{value}</span>
    ) : (
        <Muted>unset</Muted>
    )
}

/* ── Icons ──────────────────────────────────────────────────────── */

function TriggerIcon({ type }: { type?: string }): React.ReactElement {
    switch (type) {
        case 'cron':
            return <CalendarClockIcon className={LEAF} />
        case 'slack':
            return <MessageSquareIcon className={LEAF} />
        case 'webhook':
            return <WebhookIcon className={LEAF} />
        case 'chat':
            return <HashIcon className={LEAF} />
        case 'mcp':
            return <ServerIcon className={LEAF} />
        default:
            return <GlobeIcon className={LEAF} />
    }
}
function ToolKindIcon({ kind }: { kind?: string }): React.ReactElement {
    if (kind === 'client') {
        return <UserIcon className={LEAF} />
    }
    if (kind === 'custom' || kind === 'custom_template') {
        return <CodeIcon className={LEAF} />
    }
    return <SparklesIcon className={LEAF} />
}
