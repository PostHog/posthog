import {
  ChatCircleIcon,
  ChatTextIcon,
  ClockIcon,
  CodeIcon,
  FingerprintIcon,
  GaugeIcon,
  GlobeIcon,
  HardDrivesIcon,
  InfoIcon,
  KeyIcon,
  LightningIcon,
  LockKeyIcon,
  PuzzlePieceIcon,
  ScrollIcon,
  SparkleIcon,
  TrashIcon,
  UserIcon,
  WarningIcon,
  WebhooksLogoIcon,
  WrenchIcon,
} from "@phosphor-icons/react";
import type {
  McpApprovalState,
  McpInstallationTool,
} from "@posthog/api-client/posthog-client";
import type {
  AgentRevisionState,
  AgentSpec,
  BundleFile,
} from "@posthog/shared/agent-platform-types";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { AddCustomServerDialog } from "@posthog/ui/features/mcp-server-manager/AddCustomServerDialog";
import { useMcpConnect } from "@posthog/ui/features/mcp-server-manager/useMcpConnect";
import { ToolPermissionList } from "@posthog/ui/features/mcp-servers/components/parts/ToolPermissionList";
import { useMcpInstallationTools } from "@posthog/ui/features/mcp-servers/hooks/useMcpInstallationTools";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Button } from "@posthog/ui/primitives/Button";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { toast } from "@posthog/ui/primitives/toast";
import { Flex, Select, Switch, Text, TextField } from "@radix-ui/themes";
import { type ReactNode, useCallback, useMemo, useState } from "react";
import { AGENT_PLATFORM_FLAG } from "../featureFlag";
import { useAgentApplication } from "../hooks/useAgentApplication";
import { useAgentEnvKeys } from "../hooks/useAgentEnvKeys";
import { useAgentRevision } from "../hooks/useAgentRevision";
import { useAgentRevisionBundle } from "../hooks/useAgentRevisionBundle";
import { useAgentRevisions } from "../hooks/useAgentRevisions";
import { useApplyAgentSpec } from "../hooks/useApplyAgentSpec";
import { useUpdateAgentDraftBundleFile } from "../hooks/useUpdateAgentDraftBundleFile";
import { triggerRequiredSecretsFor } from "../utils/triggerSecrets";
import { AgentDetailEmptyState, AgentDetailLayout } from "./AgentDetailLayout";
import { AgentModelConfig } from "./AgentModelConfig";
import { AgentRevisionBar } from "./AgentRevisionBar";
import { CopyButton } from "./CopyButton";
import { CronFireButton } from "./CronFireButton";
import { FileExplorer, type FileTreeNode } from "./FileExplorer";
import { SecretEditor } from "./SecretEditor";
import { SlackSetupCard } from "./SlackSetupCard";
import { ToolSourcePanel } from "./ToolSourcePanel";

// Value readers — spec items are loosely typed on the wire.
function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}
function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}
function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

const ICON = { size: 14, className: "shrink-0 text-gray-10" } as const;
const USAGE_HOST = "https://<ingress-host>";

/** Context threaded to every detail body. */
interface Ctx {
  idOrSlug: string;
  revisionId: string;
  /** Application UUID — needed to branch a new draft on save. */
  applicationId?: string;
  /** State of the revision being viewed — gates the editable .md surface and drives draft-only edit vs auto-clone. */
  revisionState: AgentRevisionState;
  ingressBaseUrl?: string;
  setKeys: string[];
  onSelect: (node: string) => void;
  /** Select a revision in the picker (used to jump to a freshly branched draft). */
  onSelectRevision?: (revisionId: string) => void;
  onOpenSession?: (sessionId: string) => void;
}

function triggerType(t: unknown): string {
  return str(rec(t).type) ?? "trigger";
}
function triggerIcon(type: string): ReactNode {
  switch (type) {
    case "cron":
      return <ClockIcon {...ICON} />;
    case "slack":
      return <ChatCircleIcon {...ICON} />;
    case "webhook":
      return <WebhooksLogoIcon {...ICON} />;
    case "chat":
      return <ChatTextIcon {...ICON} />;
    case "mcp":
      return <HardDrivesIcon {...ICON} />;
    default:
      return <GlobeIcon {...ICON} />;
  }
}
function authModes(t: unknown): string[] {
  const modes = rec(rec(t).auth).modes;
  return (Array.isArray(modes) ? modes : []).map(
    (m) => str(rec(m).type) ?? "?",
  );
}
function isPublic(t: unknown): boolean {
  return authModes(t).includes("public");
}
function toolId(t: unknown): string {
  return str(rec(t).id) ?? "tool";
}
function toolIcon(kind: string | undefined): ReactNode {
  if (kind === "client") return <UserIcon {...ICON} />;
  if (kind === "custom") return <CodeIcon {...ICON} />;
  return <SparkleIcon {...ICON} />;
}
function shortName(id: string): string {
  const slash = id.lastIndexOf("/");
  return slash >= 0 ? id.slice(slash + 1) : id;
}
function missingSecretsFor(t: unknown, setKeys: string[]): string[] {
  return triggerRequiredSecretsFor(t)
    .map((s) => s.key)
    .filter((k) => !setKeys.includes(k));
}
function mcpMissingSecrets(m: unknown, setKeys: string[]): string[] {
  return arr(rec(m).secrets)
    .filter((s): s is string => typeof s === "string")
    .filter((k) => !setKeys.includes(k));
}

function allSecretKeys(spec: AgentSpec, setKeys: string[]): string[] {
  const set = new Set<string>(
    arr(spec.secrets).filter((s): s is string => typeof s === "string"),
  );
  for (const t of arr(spec.triggers))
    for (const s of triggerRequiredSecretsFor(t)) set.add(s.key);
  for (const k of setKeys) set.add(k);
  return [...set].sort();
}

// --- Identity providers (the credential axis) ---
// `spec.identity_providers[]` are the providers an asker can link against so the
// agent acts AS them when a tool/MCP needs it. Two consumers are declared in the
// spec and cross-linked here: custom tools (`requires_identity`) and MCP servers
// (`auth.provider`). Native @posthog/* tools declare their provider intrinsically
// in the tool registry, so they don't appear in the spec — noted in the UI.
function identityProviders(spec: AgentSpec): unknown[] {
  return arr(spec.identity_providers);
}
function providerId(p: unknown): string {
  return str(rec(p).id) ?? "provider";
}
function toolRequiresIdentity(t: unknown): string | undefined {
  return str(rec(t).requires_identity);
}
function mcpProvider(m: unknown): string | undefined {
  return str(rec(rec(m).auth).provider);
}

// `spec.authoritative_provider` = the one identity_providers[] id that gates
// admission. It can only be authoritative if it proves a subject (kind posthog,
// or oauth2 + userinfo_url) — mirrors AgentSpecSchema.superRefine.
// The leading NUL byte makes this sentinel structurally impossible as a
// user-typed provider id, so it can't collide with a real Select.Item value.
const NONE_PROVIDER = "\0none";
function authoritativeProviderId(spec: AgentSpec): string | undefined {
  return str(spec.authoritative_provider);
}
function establishesIdentity(p: unknown): boolean {
  const r = rec(p);
  const kind = str(r.kind);
  return kind === "posthog" || (kind === "oauth2" && !!str(r.userinfo_url));
}

// --- Per-agent MCP tool permissions (agent-level shared connection) ---
// The spec carries allow/approve/deny; the shared ToolPermissionList speaks the
// mcp_store vocabulary (approved/needs_approval/do_not_use). Map at the boundary
// so that component is reused verbatim.
type ToolApprovalLevel = "allow" | "approve" | "deny";
// New connections start safe-by-default: every tool parks for approval until the
// owner relaxes specific tools. Mirrors the runner's fallback.
const DEFAULT_TOOL_APPROVAL: ToolApprovalLevel = "approve";
const LEVEL_TO_APPROVAL: Record<ToolApprovalLevel, McpApprovalState> = {
  allow: "approved",
  approve: "needs_approval",
  deny: "do_not_use",
};
const APPROVAL_TO_LEVEL: Record<McpApprovalState, ToolApprovalLevel> = {
  approved: "allow",
  needs_approval: "approve",
  do_not_use: "deny",
};
function toToolApprovalLevel(v: unknown): ToolApprovalLevel | undefined {
  return v === "allow" || v === "approve" || v === "deny" ? v : undefined;
}
/** The per-tool override `level` declared in `mcps[].tools[]`, keyed by name. */
function toolLevelOverrides(mcpEntry: unknown): Map<string, ToolApprovalLevel> {
  const out = new Map<string, ToolApprovalLevel>();
  for (const t of arr(rec(mcpEntry).tools)) {
    if (typeof t === "object" && t) {
      const name = str(rec(t).name);
      const level = toToolApprovalLevel(rec(t).level);
      if (name && level) out.set(name, level);
    }
  }
  return out;
}
interface IdentityConsumers {
  tools: string[];
  mcps: string[];
}
function identityConsumers(spec: AgentSpec, id: string): IdentityConsumers {
  return {
    tools: arr(spec.tools).flatMap((t) =>
      toolRequiresIdentity(t) === id ? [toolId(t)] : [],
    ),
    mcps: arr(spec.mcps).flatMap((m) =>
      mcpProvider(m) === id ? [str(rec(m).id) ?? "mcp"] : [],
    ),
  };
}
function consumerCount(c: IdentityConsumers): number {
  return c.tools.length + c.mcps.length;
}

function WarnBadge({ title }: { title: string }) {
  return (
    <span title={title}>
      <WarningIcon size={13} className="text-amber-10" />
    </span>
  );
}

function buildTree(spec: AgentSpec, setKeys: string[]): FileTreeNode {
  // Order chosen for how operators read an agent: what it is, what starts it,
  // what it needs, what it knows, what it can do.
  const children: FileTreeNode[] = [
    {
      type: "file",
      name: "instructions",
      path: "cfg:instructions",
      icon: <ScrollIcon {...ICON} />,
    },
    {
      type: "file",
      name: "model",
      path: "cfg:model",
      icon: <SparkleIcon {...ICON} />,
    },
  ];

  // Above triggers: admission gates whether any trigger can start a session.
  const identities = identityProviders(spec);
  const authProviderId = authoritativeProviderId(spec);
  children.push({
    type: "folder",
    name: "auth & identity",
    path: "cfg:identities",
    icon: <FingerprintIcon {...ICON} />,
    children: identities.map((p) => {
      const id = providerId(p);
      const used = consumerCount(identityConsumers(spec, id));
      return {
        type: "file" as const,
        name: id,
        path: `cfg:identity/${id}`,
        icon: <FingerprintIcon {...ICON} />,
        trailing:
          id === authProviderId ? (
            <Badge color="iris">auth</Badge>
          ) : used === 0 ? (
            <Badge color="amber">unused</Badge>
          ) : undefined,
      };
    }),
  });

  const triggers = arr(spec.triggers);
  children.push({
    type: "folder",
    name: "triggers",
    path: "cfg:triggers",
    icon: <LightningIcon {...ICON} />,
    children: triggers.map((t, i) => {
      const type = triggerType(t);
      const missing = missingSecretsFor(t, setKeys);
      return {
        type: "file" as const,
        name: type,
        path: `cfg:trigger/${i}`,
        icon: triggerIcon(type),
        trailing:
          missing.length > 0 ? (
            <WarnBadge title={`Needs secret(s): ${missing.join(", ")}`} />
          ) : isPublic(t) ? (
            <Badge color="amber">public</Badge>
          ) : undefined,
      };
    }),
  });

  const secretKeys = allSecretKeys(spec, setKeys);
  children.push({
    type: "folder",
    name: "secrets",
    path: "cfg:secrets",
    icon: <KeyIcon {...ICON} />,
    children: secretKeys.map((key) => ({
      type: "file" as const,
      name: key,
      path: `cfg:secret/${key}`,
      icon: <KeyIcon {...ICON} />,
      trailing: setKeys.includes(key) ? undefined : (
        <Badge color="amber">not set</Badge>
      ),
    })),
  });

  const skills = arr(spec.skills);
  children.push({
    type: "folder",
    name: "skills",
    path: "cfg:skills",
    icon: <PuzzlePieceIcon {...ICON} />,
    children: skills.map((s) => {
      const r = rec(s);
      const id = str(r.id) ?? str(r.path) ?? "skill";
      return {
        type: "file" as const,
        name: id,
        path: `cfg:skill/${id}`,
        description: str(r.description),
        icon: <PuzzlePieceIcon {...ICON} />,
      };
    }),
  });

  const tools = arr(spec.tools);
  children.push({
    type: "folder",
    name: "tools",
    path: "cfg:tools",
    icon: <WrenchIcon {...ICON} />,
    children: tools.map((t) => {
      const r = rec(t);
      const id = toolId(t);
      return {
        type: "file" as const,
        name: shortName(id),
        path: `cfg:tool/${id}`,
        icon: toolIcon(str(r.kind)),
        trailing:
          r.requires_approval === true ? (
            <LockKeyIcon size={11} className="text-amber-10" />
          ) : undefined,
      };
    }),
  });

  // Top-level authorable sections always render — even with no entries — so the
  // add/connect affordance is reachable on a fresh agent (you add MCP servers,
  // tools, skills, triggers, secrets and identities from the empty section).
  const mcps = arr(spec.mcps);
  children.push({
    type: "folder",
    name: "mcps",
    path: "cfg:mcps",
    icon: <HardDrivesIcon {...ICON} />,
    children: mcps.map((m) => {
      const id = str(rec(m).id) ?? "mcp";
      const missing = mcpMissingSecrets(m, setKeys);
      return {
        type: "file" as const,
        name: id,
        path: `cfg:mcp/${id}`,
        icon: <HardDrivesIcon {...ICON} />,
        trailing:
          missing.length > 0 ? (
            <WarnBadge title={`Needs secret(s): ${missing.join(", ")}`} />
          ) : undefined,
      };
    }),
  });

  children.push({
    type: "file",
    name: "limits",
    path: "cfg:limits",
    icon: <GaugeIcon {...ICON} />,
  });

  return { type: "folder", name: "root", children };
}

export function AgentConfigurationPane({
  idOrSlug,
  selectedNode,
  onSelectNode,
  selectedRevisionId,
  onSelectRevision,
  onOpenSession,
}: {
  idOrSlug: string;
  selectedNode: string | null;
  onSelectNode: (node: string) => void;
  /** Revision viewed in the explorer (URL `?revision=`); defaults to live. */
  selectedRevisionId: string | null;
  onSelectRevision: (revisionId: string) => void;
  onOpenSession?: (sessionId: string) => void;
}) {
  const { data: application } = useAgentApplication(idOrSlug);
  const { data: revisions } = useAgentRevisions(idOrSlug);

  // The explorer shows the selected revision, falling back to live then newest.
  const revisionId =
    selectedRevisionId ??
    application?.live_revision ??
    revisions?.[0]?.id ??
    null;

  const { data: revision, isLoading } = useAgentRevision(idOrSlug, revisionId);
  const { data: bundle } = useAgentRevisionBundle(idOrSlug, revisionId);
  const { data: envKeys } = useAgentEnvKeys(idOrSlug, revisionId);

  const spec = revision?.spec ?? null;
  const setKeys = useMemo(() => envKeys ?? [], [envKeys]);
  const files = useMemo(() => bundle ?? [], [bundle]);
  const tree = useMemo(
    () => (spec ? buildTree(spec, setKeys) : null),
    [spec, setKeys],
  );
  const node = selectedNode ?? "cfg:instructions";

  const ctx: Ctx | null = revisionId
    ? {
        idOrSlug,
        revisionId,
        applicationId: application?.id,
        // `revision` may still be loading; fall back to the picker's view so
        // the editable-on-draft gating doesn't briefly flash on for a ready
        // revision while data resolves. Default to `ready` (immutable).
        revisionState:
          revision?.state ??
          revisions?.find((r) => r.id === revisionId)?.state ??
          "ready",
        ingressBaseUrl: application?.ingress_base_url ?? undefined,
        setKeys,
        onSelect: onSelectNode,
        onSelectRevision,
        onOpenSession,
      }
    : null;

  const bar =
    application && revisions && revisions.length > 0 ? (
      <AgentRevisionBar
        idOrSlug={idOrSlug}
        agent={application}
        revisions={revisions}
        selectedRevisionId={revisionId}
        onSelectRevision={onSelectRevision}
      />
    ) : null;

  return (
    <AgentDetailLayout
      idOrSlug={idOrSlug}
      activeTab="configuration"
      fill
      configRevision={revisionId}
    >
      {!revisionId ? (
        <div className="p-6">
          <AgentDetailEmptyState
            title="No revisions yet"
            description="This agent has no revisions, so there's no configuration to show."
          />
        </div>
      ) : !spec || !ctx ? (
        <Flex direction="column" className="h-full min-h-0">
          {bar}
          <div className="p-6">
            {isLoading ? (
              <div className="h-40 animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)" />
            ) : (
              <AgentDetailEmptyState
                title="Couldn't load configuration"
                description="This revision's spec could not be loaded."
              />
            )}
          </div>
        </Flex>
      ) : (
        <Flex direction="column" className="h-full min-h-0">
          {bar}
          <div className="min-h-0 flex-1">
            <FileExplorer
              tree={tree}
              selectedPath={node}
              onSelectPath={onSelectNode}
              storageKey="agent-config-explorer"
            >
              <DetailPane node={node} spec={spec} files={files} ctx={ctx} />
            </FileExplorer>
          </div>
        </Flex>
      )}
    </AgentDetailLayout>
  );
}

const SECTION_INFO: Record<string, string> = {
  "cfg:model":
    "How the agent picks its model. `auto` resolves a level (low/medium/high) to a maintained cross-provider list at runtime; `manual` pins an explicit priority list. `reasoning` sets the extended-thinking budget.",
  "cfg:instructions":
    "The agent's entrypoint prompt (agent.md) — the always-on system instructions.",
  "cfg:triggers": "What can start a session — chat, webhook, mcp, slack, cron.",
  "cfg:tools": "The callable functions this agent has, by where they run.",
  "cfg:skills":
    "Markdown playbooks the agent loads on demand. Only the description is in the prompt until loaded.",
  "cfg:mcps": "Remote MCP servers the agent connects to at session start.",
  "cfg:identities":
    "Identity providers an asker links against, so the agent can act AS them when a tool or MCP call needs it (per-asker, binding: principal). Admission: pick ONE as the authoritative provider to gate every session — a verified identity from it is required before any session runs (Slack, HTTP, …).",
  "cfg:secrets": "Env keys this agent reads. Values are never shown.",
  "cfg:limits": "Hard caps on a single run.",
};

function DetailPane({
  node,
  spec,
  files,
  ctx,
}: {
  node: string;
  spec: AgentSpec;
  files: BundleFile[];
  ctx: Ctx;
}) {
  const [section, ...idParts] = node.replace(/^cfg:/, "").split("/");
  const id = idParts.join("/");
  const meta = nodeHeader(section, id, spec);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <DetailHeader
        icon={meta.icon}
        title={meta.title}
        node={node}
        info={SECTION_INFO[`cfg:${section}`]}
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <DetailBody
          section={section}
          id={id}
          spec={spec}
          files={files}
          ctx={ctx}
        />
      </div>
    </div>
  );
}

function nodeHeader(
  section: string,
  id: string,
  spec: AgentSpec,
): { icon: ReactNode; title: string } {
  switch (section) {
    case "model":
      return { icon: <SparkleIcon {...ICON} />, title: "Model" };
    case "instructions":
      return { icon: <ScrollIcon {...ICON} />, title: "Instructions" };
    case "triggers":
      return { icon: <LightningIcon {...ICON} />, title: "Triggers" };
    case "trigger": {
      const type = triggerType(arr(spec.triggers)[Number(id)]);
      return { icon: triggerIcon(type), title: `${type} trigger` };
    }
    case "tools":
      return { icon: <WrenchIcon {...ICON} />, title: "Tools" };
    case "tool":
      return { icon: <WrenchIcon {...ICON} />, title: shortName(id) };
    case "skills":
      return { icon: <PuzzlePieceIcon {...ICON} />, title: "Skills" };
    case "skill":
      return { icon: <PuzzlePieceIcon {...ICON} />, title: id };
    case "mcps":
      return { icon: <HardDrivesIcon {...ICON} />, title: "MCP servers" };
    case "mcp":
      return { icon: <HardDrivesIcon {...ICON} />, title: id };
    case "identities":
      return { icon: <FingerprintIcon {...ICON} />, title: "Auth & identity" };
    case "identity":
      return { icon: <FingerprintIcon {...ICON} />, title: id };
    case "secrets":
      return { icon: <KeyIcon {...ICON} />, title: "Secrets" };
    case "secret":
      return { icon: <KeyIcon {...ICON} />, title: id };
    case "limits":
      return { icon: <GaugeIcon {...ICON} />, title: "Limits" };
    default:
      return { icon: <SparkleIcon {...ICON} />, title: section };
  }
}

function DetailHeader({
  icon,
  title,
  node,
  info,
}: {
  icon: ReactNode;
  title: string;
  node: string;
  info?: string;
}) {
  const [showInfo, setShowInfo] = useState(false);
  return (
    <div className="shrink-0 border-(--gray-5) border-b px-5 py-3">
      <Flex align="center" gap="2">
        {icon}
        <Text className="font-semibold text-[14px] text-gray-12">{title}</Text>
        {info ? (
          <button
            type="button"
            onClick={() => setShowInfo((s) => !s)}
            className="text-gray-10 hover:text-gray-12"
            aria-label="About this section"
          >
            <InfoIcon size={14} />
          </button>
        ) : null}
        <span className="ml-auto truncate rounded-(--radius-1) border border-border bg-(--gray-2) px-1.5 py-0.5 text-[10.5px] text-gray-10 [font-family:var(--font-mono)]">
          {node}
        </span>
      </Flex>
      {showInfo && info ? (
        <Text className="mt-2 block text-[12px] text-gray-11 leading-snug">
          {info}
        </Text>
      ) : null}
    </div>
  );
}

function DetailBody({
  section,
  id,
  spec,
  files,
  ctx,
}: {
  section: string;
  id: string;
  spec: AgentSpec;
  files: BundleFile[];
  ctx: Ctx;
}) {
  switch (section) {
    case "model":
      return <ModelBody key={ctx.revisionId} spec={spec} ctx={ctx} />;
    case "instructions":
      return (
        <BundleFileBody
          file={byPath(files, "agent.md")}
          emptyLabel="No agent.md in this revision."
          editable={
            ctx.revisionState === "draft"
              ? {
                  idOrSlug: ctx.idOrSlug,
                  revisionId: ctx.revisionId,
                  path: "agent.md",
                }
              : undefined
          }
        />
      );
    case "triggers":
      return <TriggersOverview spec={spec} ctx={ctx} />;
    case "trigger":
      return <TriggerBody trigger={arr(spec.triggers)[Number(id)]} ctx={ctx} />;
    case "tools":
      return <ToolsOverview spec={spec} ctx={ctx} />;
    case "tool":
      return (
        <ToolBody
          tool={findById(arr(spec.tools), id)}
          files={files}
          id={id}
          spec={spec}
          ctx={ctx}
        />
      );
    case "skills":
      return <SkillsOverview spec={spec} ctx={ctx} />;
    case "skill":
      return (
        <SkillBody
          skill={findById(arr(spec.skills), id)}
          file={byPath(files, `skills/${id}/SKILL.md`)}
          id={id}
          ctx={ctx}
        />
      );
    case "mcps":
      return <McpsOverview spec={spec} ctx={ctx} />;
    case "mcp":
      return (
        <McpBody mcp={findById(arr(spec.mcps), id)} spec={spec} ctx={ctx} />
      );
    case "identities":
      return <IdentitiesOverview spec={spec} ctx={ctx} />;
    case "identity":
      return (
        <IdentityBody
          provider={findById(identityProviders(spec), id)}
          id={id}
          spec={spec}
          ctx={ctx}
        />
      );
    case "secrets":
      return <SecretsOverview spec={spec} ctx={ctx} />;
    case "secret":
      return (
        <SecretBody
          keyName={id}
          setKeys={ctx.setKeys}
          idOrSlug={ctx.idOrSlug}
          revisionId={ctx.revisionId}
        />
      );
    case "limits":
      return <LimitsBody spec={spec} />;
    default:
      return <Muted>Nothing to show.</Muted>;
  }
}

function findById(items: unknown[], id: string): unknown {
  return items.find((it) => str(rec(it).id) === id);
}
function byPath(files: BundleFile[], path: string): BundleFile | undefined {
  return files.find((f) => f.path === path);
}

function ModelBody({ spec, ctx }: { spec: AgentSpec; ctx: Ctx }) {
  return (
    <AgentModelConfig
      spec={spec}
      idOrSlug={ctx.idOrSlug}
      applicationId={ctx.applicationId}
      revisionId={ctx.revisionId}
      revisionState={ctx.revisionState}
      onSelectRevision={ctx.onSelectRevision}
    />
  );
}

function LimitsBody({ spec }: { spec: AgentSpec }) {
  const entries = Object.entries(spec.limits ?? {}).filter(
    ([, v]) => v != null,
  );
  if (entries.length === 0) return <Muted>No limits configured.</Muted>;
  return (
    <Flex direction="column" gap="2">
      {entries.map(([k, v]) => (
        <Row key={k} label={k.replace(/_/g, " ")} value={String(v)} />
      ))}
    </Flex>
  );
}

const TRIGGER_EXPLAINER: Record<string, string> = {
  cron: "Fires on a schedule from the platform scheduler — no inbound endpoint, no inbound auth.",
  slack:
    "Responds to Slack mentions + thread replies for trusted workspaces. Auth is intrinsic — every request is verified by Slack request signature.",
  webhook:
    "A POST to the webhook endpoint starts a session — the raw JSON body becomes the first message. Callers satisfy one of the auth modes below.",
  chat: "Interactive sessions over /run + /send. Every caller is authenticated per the auth modes below.",
  mcp: "Exposes the agent as an MCP server over streamable-HTTP; clients authenticate per the auth modes below.",
};

const AUTH_MODE_BLURB: Record<string, string> = {
  public:
    "Anonymous — anyone can call. Explicitly acknowledged as public exposure.",
  posthog:
    "A PostHog credential (personal API key / OAuth) — end-user identity.",
  jwt: "Signed JWT verified with a per-agent secret.",
  shared_secret: "A shared secret sent in a named header (webhook-style).",
  posthog_internal: "PostHog server-to-server internal token.",
};

const DECLARATIVE_TRIGGERS = new Set(["webhook", "chat", "mcp"]);

const TRIGGER_ENDPOINTS: Record<
  string,
  { method: string; path: string; blurb: string }[]
> = {
  chat: [
    { method: "POST", path: "/run", blurb: "start a session" },
    { method: "POST", path: "/send", blurb: "send a follow-up" },
    { method: "GET", path: "/listen", blurb: "stream events (SSE)" },
  ],
  webhook: [
    {
      method: "POST",
      path: "/webhook",
      blurb: "JSON body becomes the first message",
    },
  ],
  mcp: [{ method: "POST", path: "/mcp", blurb: "HTTP MCP server" }],
  slack: [
    { method: "POST", path: "/slack/events", blurb: "Event Subscriptions URL" },
    {
      method: "POST",
      path: "/slack/interactivity",
      blurb: "Interactivity URL",
    },
  ],
};

function ingressBase(ctx: Ctx): string {
  return (ctx.ingressBaseUrl ?? `${USAGE_HOST}/agents/${ctx.idOrSlug}`).replace(
    /\/$/,
    "",
  );
}

function TriggersOverview({ spec, ctx }: { spec: AgentSpec; ctx: Ctx }) {
  const triggers = arr(spec.triggers);
  if (triggers.length === 0) return <Muted>No triggers configured.</Muted>;
  const base = ingressBase(ctx);
  const withEndpoints = triggers.filter(
    (t) => TRIGGER_ENDPOINTS[triggerType(t)],
  );
  return (
    <Flex direction="column" gap="4">
      <Muted>What can start a session — {triggers.length} configured.</Muted>
      <Flex direction="column" gap="2">
        {triggers.map((t, i) => {
          const type = triggerType(t);
          const cfg = rec(rec(t).config);
          const disc =
            str(cfg.name) ?? str(cfg.path) ?? str(cfg.channel_id) ?? String(i);
          const missing = missingSecretsFor(t, ctx.setKeys);
          return (
            <JumpRow
              key={`${type}:${disc}`}
              icon={triggerIcon(type)}
              title={type}
              subtitle={TRIGGER_EXPLAINER[type]}
              trailing={
                missing.length > 0 ? (
                  <WarnBadge title={`Needs: ${missing.join(", ")}`} />
                ) : isPublic(t) ? (
                  <Badge color="amber">public</Badge>
                ) : (
                  <Badge color="gray">private</Badge>
                )
              }
              onClick={() => ctx.onSelect(`cfg:trigger/${i}`)}
            />
          );
        })}
      </Flex>
      {withEndpoints.length > 0 ? (
        <div>
          <Subhead>Endpoints</Subhead>
          {!ctx.ingressBaseUrl ? (
            <Muted>
              No public ingress URL is configured — placeholder host shown.
            </Muted>
          ) : null}
          <Flex direction="column" gap="1" className="mt-1.5">
            {withEndpoints.flatMap((t) =>
              (TRIGGER_ENDPOINTS[triggerType(t)] ?? []).map((ep) => {
                const url = `${base}${ep.path}`;
                return (
                  <Flex
                    key={`${triggerType(t)}${ep.path}`}
                    align="center"
                    gap="2"
                    className="text-[11px]"
                  >
                    <span className="w-8 shrink-0 text-gray-10 [font-family:var(--font-mono)]">
                      {ep.method}
                    </span>
                    <code className="min-w-0 flex-1 truncate text-gray-12 [font-family:var(--font-mono)]">
                      {url}
                    </code>
                    <CopyButton text={url} />
                  </Flex>
                );
              }),
            )}
          </Flex>
        </div>
      ) : null}
    </Flex>
  );
}

// Short, operator-facing hints for the well-known trigger config fields. Keyed
// by field name (shared across trigger types); unknown fields render with no
// hint. Mirrors the field docs on `TriggerSchema` in agent-shared/src/spec.
const TRIGGER_FIELD_HINTS: Record<string, string> = {
  mention_only:
    "Only @-mentions start a session; plain channel messages are ignored.",
  auto_resume_threads:
    "Replies in an already-open thread continue without re-mentioning the bot.",
  allow_workspace_participants:
    "Any trusted-workspace user can advance the thread, not just the opener.",
  allow_direct_messages:
    "The bot also answers DMs and group DMs, not just channel mentions.",
  ack_reaction:
    "Emoji the bot adds the instant it receives a message, for sub-3s feedback.",
  trusted_workspaces:
    'Slack workspaces allowed to invoke this agent ("*" = any workspace).',
  channel_id: "The channel this trigger is scoped to.",
  schedule: "Cron expression for when the job fires.",
  timezone: "IANA timezone the schedule is evaluated in.",
  prompt:
    "The task handed to the agent as the first message when the cron fires.",
  external_key: "Reuses one rolling session across firings when set.",
  catch_up: "What to fire for runs missed during downtime.",
  max_catch_up_age_seconds: "How far back catch-up will look for missed runs.",
  name: "Stable handle for this cron job (used in session metadata).",
  allow_restart:
    "A /send to a closed session reopens it instead of returning 410.",
  path: "URL path the webhook is mounted at.",
};

function isLongText(v: string): boolean {
  return v.length > 64 || v.includes("\n");
}

/** A single trigger config field rendered by value type: booleans as on/off
 *  pills, string arrays as chips, long text in a block, scalars inline. */
function OptionRow({
  label,
  value,
  hint,
}: {
  label: string;
  value: unknown;
  hint?: string;
}) {
  const human = label.replace(/_/g, " ");
  if (typeof value === "boolean") {
    return (
      <OptionCard
        label={human}
        hint={hint}
        trailing={
          <Badge color={value ? "green" : "gray"}>{value ? "on" : "off"}</Badge>
        }
      />
    );
  }
  if (Array.isArray(value)) {
    const items = value.map((x) =>
      typeof x === "string" ? x : JSON.stringify(x),
    );
    return (
      <OptionCard label={human} hint={hint}>
        <Flex gap="1.5" wrap="wrap">
          {items.length === 0 ? (
            <Text className="text-[12px] text-gray-10">none</Text>
          ) : (
            items.map((x, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: display-only chips; values (e.g. trusted_workspaces) can repeat
              <Badge key={i} color="gray">
                {x}
              </Badge>
            ))
          )}
        </Flex>
      </OptionCard>
    );
  }
  if (typeof value === "string" && isLongText(value)) {
    return (
      <OptionCard label={human} hint={hint}>
        <Text className="block whitespace-pre-wrap text-[12.5px] text-gray-12 leading-snug">
          {value}
        </Text>
      </OptionCard>
    );
  }
  const display =
    typeof value === "string" || typeof value === "number"
      ? String(value)
      : JSON.stringify(value);
  return (
    <OptionCard
      label={human}
      hint={hint}
      trailing={
        <Text className="truncate text-[12.5px] text-gray-12 [font-family:var(--font-mono)]">
          {display}
        </Text>
      }
    />
  );
}

function OptionCard({
  label,
  hint,
  trailing,
  children,
}: {
  label: string;
  hint?: string;
  trailing?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-(--radius-2) border border-border bg-(--gray-2) px-3 py-2">
      <Flex align="center" justify="between" gap="3">
        <Text className="shrink-0 text-[11px] text-gray-10 uppercase tracking-wide">
          {label}
        </Text>
        {/* No `shrink-0`: the label is shrink-0, so letting this side shrink
            gives an inner `truncate` a width bound to ellipsize a long scalar
            against (small trailing chips/buttons are unaffected). */}
        {trailing ? <span className="min-w-0">{trailing}</span> : null}
      </Flex>
      {hint ? (
        <Text className="mt-0.5 block text-[11px] text-gray-10 leading-snug">
          {hint}
        </Text>
      ) : null}
      {children ? <div className="mt-1.5">{children}</div> : null}
    </div>
  );
}

function TriggerOptions({
  type,
  config,
}: {
  type: string;
  config: Record<string, unknown>;
}) {
  const entries = Object.entries(config);
  if (entries.length === 0)
    return <Muted>No options for the {type} trigger.</Muted>;
  return (
    <Flex direction="column" gap="2">
      {entries.map(([k, v]) => (
        <OptionRow key={k} label={k} value={v} hint={TRIGGER_FIELD_HINTS[k]} />
      ))}
    </Flex>
  );
}

function TriggerBody({ trigger, ctx }: { trigger: unknown; ctx: Ctx }) {
  const r = rec(trigger);
  const type = triggerType(trigger);
  const config = rec(r.config);
  const modes = authModes(trigger);
  const missing = missingSecretsFor(trigger, ctx.setKeys);
  const cronName = type === "cron" ? str(config.name) : undefined;

  return (
    <Flex direction="column" gap="3">
      {TRIGGER_EXPLAINER[type] ? (
        <Muted>{TRIGGER_EXPLAINER[type]}</Muted>
      ) : null}

      <Row label="type" value={type} mono />

      <div>
        <Subhead>Options</Subhead>
        <div className="mt-1.5">
          <TriggerOptions type={type} config={config} />
        </div>
      </div>

      {missing.length > 0 ? (
        <Attention>
          <Text className="text-[12px] text-gray-12">
            Missing required secret{missing.length > 1 ? "s" : ""}:
          </Text>
          <Flex gap="1.5" wrap="wrap" className="mt-1.5">
            {missing.map((key) => (
              <Button
                key={key}
                size="1"
                variant="soft"
                color="amber"
                onClick={() => ctx.onSelect(`cfg:secret/${key}`)}
              >
                Set {key}
              </Button>
            ))}
          </Flex>
        </Attention>
      ) : null}

      <div>
        <Subhead>Auth</Subhead>
        {DECLARATIVE_TRIGGERS.has(type) ? (
          modes.length > 0 ? (
            <Flex direction="column" gap="1.5" className="mt-1">
              {modes.map((m) => (
                <Flex key={m} align="baseline" gap="2">
                  <Badge color={m === "public" ? "amber" : "gray"}>{m}</Badge>
                  <Text className="text-[11.5px] text-gray-10">
                    {AUTH_MODE_BLURB[m] ?? ""}
                  </Text>
                </Flex>
              ))}
            </Flex>
          ) : (
            <Muted>No auth modes configured.</Muted>
          )
        ) : (
          <Muted>
            Intrinsic — verified by the trigger's own protocol, not
            configurable.
          </Muted>
        )}
        {isPublic(trigger) ? (
          <Attention tone="warn">
            This trigger is public — it accepts anonymous, unauthenticated
            callers.
          </Attention>
        ) : null}
      </div>

      {cronName ? (
        <div>
          <Subhead>Test</Subhead>
          <CronFireButton
            idOrSlug={ctx.idOrSlug}
            revisionId={ctx.revisionId}
            cronName={cronName}
            onFired={(sessionId) => ctx.onOpenSession?.(sessionId)}
          />
        </div>
      ) : null}

      <TriggerUsage trigger={trigger} ctx={ctx} />

      {type === "slack" ? (
        <SlackSetupCard idOrSlug={ctx.idOrSlug} revisionId={ctx.revisionId} />
      ) : null}
    </Flex>
  );
}

function authHeaderExample(modes: string[], trigger: unknown): string {
  if (modes.includes("public") && modes.length === 1) return "";
  if (modes.includes("shared_secret")) {
    const m = (arr(rec(rec(trigger).auth).modes) as unknown[]).find(
      (x) => str(rec(x).type) === "shared_secret",
    );
    const header = str(rec(m).header) ?? "X-Webhook-Secret";
    return `  -H '${header}: <your-secret>' \\\n`;
  }
  if (modes.includes("posthog"))
    return "  -H 'Authorization: Bearer <POSTHOG_API_KEY>' \\\n";
  if (modes.includes("jwt"))
    return "  -H 'Authorization: Bearer <SIGNED_JWT>' \\\n";
  if (modes.includes("posthog_internal"))
    return "  -H 'x-posthog-internal: <INTERNAL_SECRET>' \\\n";
  return "";
}

function TriggerUsage({ trigger, ctx }: { trigger: unknown; ctx: Ctx }) {
  const type = triggerType(trigger);
  const base = ingressBase(ctx);
  const modes = authModes(trigger);
  const authHeader = authHeaderExample(modes, trigger);
  let examples: { title: string; code: string }[] = [];
  if (type === "webhook") {
    examples = [
      {
        title: "Send a webhook",
        code: `curl -X POST '${base}/webhook' \\\n${authHeader}  -H 'Content-Type: application/json' \\\n  -d '{"message":"hello"}'`,
      },
    ];
  } else if (type === "chat") {
    examples = [
      {
        title: "Start a session",
        code: `curl -X POST '${base}/run' \\\n${authHeader}  -H 'Content-Type: application/json' \\\n  -d '{"message":"hello"}'`,
      },
    ];
  } else if (type === "mcp") {
    examples = [
      {
        title: "Add to an MCP client",
        code: `claude mcp add --transport http ${ctx.idOrSlug} '${base}/mcp'`,
      },
    ];
  }
  if (examples.length === 0) return null;
  return (
    <div>
      <Subhead>Usage</Subhead>
      <Flex direction="column" gap="2" className="mt-1">
        {examples.map((ex) => (
          <div key={ex.title}>
            <Text className="mb-1 block text-[11px] text-gray-10">
              {ex.title}
            </Text>
            <CodeBlock>{ex.code}</CodeBlock>
          </div>
        ))}
      </Flex>
    </div>
  );
}

function ToolsOverview({ spec, ctx }: { spec: AgentSpec; ctx: Ctx }) {
  const tools = arr(spec.tools);
  if (tools.length === 0) return <Muted>No tools.</Muted>;
  const counts = tools.reduce<Record<string, number>>((acc, t) => {
    const kind = str(rec(t).kind) ?? "native";
    acc[kind] = (acc[kind] ?? 0) + 1;
    return acc;
  }, {});
  return (
    <Flex direction="column" gap="3">
      <Muted>
        {Object.entries(counts)
          .map(([k, n]) => `${n} ${k}`)
          .join(" · ")}
      </Muted>
      <Flex direction="column" gap="2">
        {tools.map((t) => {
          const r = rec(t);
          const id = toolId(t);
          return (
            <JumpRow
              key={id}
              icon={toolIcon(str(r.kind))}
              title={shortName(id)}
              subtitle={str(r.description)}
              trailing={
                r.requires_approval === true ? (
                  <Badge color="amber">approval</Badge>
                ) : undefined
              }
              onClick={() => ctx.onSelect(`cfg:tool/${id}`)}
            />
          );
        })}
      </Flex>
    </Flex>
  );
}

/** Read `{ description, args_schema }` from a tool's schema.json bundle file,
 *  falling back to the spec description. v0 tool edits change source only, so we
 *  round-trip these unchanged on save. */
function parseToolSchema(
  content: string | undefined,
  fallbackDescription: string | undefined,
): { description: string; args_schema: Record<string, unknown> } {
  if (content) {
    try {
      const parsed = JSON.parse(content) as {
        description?: unknown;
        args_schema?: unknown;
      };
      return {
        description: str(parsed.description) ?? fallbackDescription ?? "",
        args_schema:
          parsed.args_schema && typeof parsed.args_schema === "object"
            ? (parsed.args_schema as Record<string, unknown>)
            : {},
      };
    } catch {
      // Malformed schema.json — fall back below rather than block editing.
    }
  }
  return { description: fallbackDescription ?? "", args_schema: {} };
}

function ToolBody({
  tool,
  files,
  id,
  spec,
  ctx,
}: {
  tool: unknown;
  files: BundleFile[];
  id: string;
  spec: AgentSpec;
  ctx: Ctx;
}) {
  const r = rec(tool);
  const kind = str(r.kind);
  const identity = toolRequiresIdentity(tool);
  const source = byPath(files, `tools/${id}/source.ts`);
  const schemaFile = byPath(files, `tools/${id}/schema.json`);
  const specDescription = str(r.description);
  // Authoring (edit/save/dry-run) lives behind the same flag as the rest of the
  // surface; custom tools are the only ones with editable source.
  const authoringEnabled = useFeatureFlag(AGENT_PLATFORM_FLAG);
  const isCustom = kind === "custom" || !!source;
  const isDraft = ctx.revisionState === "draft";
  const canAuthor = authoringEnabled && isCustom && isDraft;
  const schema = useMemo(
    () => parseToolSchema(schemaFile?.content, specDescription),
    [schemaFile?.content, specDescription],
  );
  return (
    <Flex direction="column" gap="2">
      <Row label="id" value={id} mono />
      {kind ? <Row label="kind" value={kind} /> : null}
      <Row
        label="approval"
        value={
          r.requires_approval === true
            ? "required before each call"
            : "not gated"
        }
      />
      {specDescription ? (
        <Text className="text-[12.5px] text-gray-11 leading-snug">
          {specDescription}
        </Text>
      ) : null}
      {identity ? (
        <IdentityLink provider={identity} spec={spec} ctx={ctx} />
      ) : null}
      {source ? (
        <ToolSourcePanel
          // Remount on revision/tool switch so the buffer + toggles reset.
          key={`${ctx.revisionId}:${id}`}
          idOrSlug={ctx.idOrSlug}
          revisionId={ctx.revisionId}
          toolId={id}
          source={source}
          description={schema.description}
          argsSchema={schema.args_schema}
          canEdit={canAuthor}
          canDryRun={authoringEnabled && isCustom}
        />
      ) : null}
    </Flex>
  );
}

/** A back-link from a tool/MCP to the identity provider it acts as. Warns when
 *  the referenced provider id isn't declared in `spec.identity_providers[]`. */
function IdentityLink({
  provider,
  spec,
  ctx,
}: {
  provider: string;
  spec: AgentSpec;
  ctx: Ctx;
}) {
  const declared = identityProviders(spec).some(
    (p) => providerId(p) === provider,
  );
  return (
    <div>
      <Subhead>Acts as identity</Subhead>
      <div className="mt-1">
        <JumpRow
          icon={<FingerprintIcon {...ICON} />}
          title={provider}
          mono
          subtitle={
            declared
              ? "per-asker linked identity"
              : "not declared in identities"
          }
          trailing={
            declared ? undefined : <Badge color="amber">undeclared</Badge>
          }
          onClick={() => ctx.onSelect(`cfg:identity/${provider}`)}
        />
      </div>
    </div>
  );
}

function SkillsOverview({ spec, ctx }: { spec: AgentSpec; ctx: Ctx }) {
  const skills = arr(spec.skills);
  if (skills.length === 0) return <Muted>No skills.</Muted>;
  return (
    <Flex direction="column" gap="3">
      <Muted>
        Markdown playbooks loaded on demand — {skills.length} here. Only the
        description is in the prompt until a skill is loaded.
      </Muted>
      <Flex direction="column" gap="2">
        {skills.map((s) => {
          const r = rec(s);
          const id = str(r.id) ?? str(r.path) ?? "skill";
          return (
            <JumpRow
              key={id}
              icon={<PuzzlePieceIcon {...ICON} />}
              title={id}
              subtitle={str(r.description)}
              onClick={() => ctx.onSelect(`cfg:skill/${id}`)}
            />
          );
        })}
      </Flex>
    </Flex>
  );
}

function SkillBody({
  skill,
  file,
  id,
  ctx,
}: {
  skill: unknown;
  file: BundleFile | undefined;
  id: string;
  ctx: Ctx;
}) {
  const r = rec(skill);
  const skillId = str(r.id) ?? id;
  const path = `skills/${skillId}/SKILL.md`;
  return (
    <Flex direction="column" gap="2">
      <Row label="id" value={skillId} mono />
      <Text className="text-[12.5px] text-gray-11 leading-snug">
        {str(r.description) ?? "No description."}
      </Text>
      <div className="mt-2">
        <Subhead>body · {path}</Subhead>
        <BundleFileBody
          file={file}
          emptyLabel="Body not in the loaded bundle."
          editable={
            ctx.revisionState === "draft"
              ? {
                  idOrSlug: ctx.idOrSlug,
                  revisionId: ctx.revisionId,
                  path,
                }
              : undefined
          }
        />
      </div>
    </Flex>
  );
}

function McpsOverview({ spec, ctx }: { spec: AgentSpec; ctx: Ctx }) {
  const mcps = arr(spec.mcps);
  const { installations, connectCustom, connectCustomPending } =
    useMcpConnect();
  const applySpec = useApplyAgentSpec(ctx.idOrSlug, ctx.applicationId);
  const [showAdd, setShowAdd] = useState(false);
  const canEdit = !!ctx.revisionState;

  // Append a new mcps[] entry referencing the chosen connection (id derived
  // from its name, url filled from the installation), then select it.
  const addFromConnection = (installId: string) => {
    const install = (installations ?? []).find((i) => i.id === installId);
    if (!install || !ctx.revisionState) return;
    const base =
      (install.display_name || install.url || "mcp")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 32) || "mcp";
    const taken = new Set(mcps.map((m) => str(rec(m).id)));
    let newId = base;
    for (let n = 2; taken.has(newId); n++) newId = `${base}-${n}`;
    const entry = {
      id: newId,
      url: install.url ?? "",
      connection: install.id,
      secrets: [] as string[],
      // Safe-by-default: every tool parks for approval until the owner relaxes
      // specific ones. Activates the per-agent permission model (vs the legacy
      // allowlist) so the runtime + the detail UI agree from the first save.
      default_tool_approval: "approve" as const,
    };
    applySpec.mutate(
      {
        revision: { id: ctx.revisionId, state: ctx.revisionState },
        spec: { ...spec, mcps: [...mcps, entry] },
      },
      {
        onSuccess: (rev) => {
          if (rev.id !== ctx.revisionId) ctx.onSelectRevision?.(rev.id);
          ctx.onSelect(`cfg:mcp/${newId}`);
        },
        onError: (e) => toast.error(e.message || "Failed to add MCP server"),
      },
    );
  };

  return (
    <Flex direction="column" gap="2">
      {mcps.length === 0 ? (
        <Muted>No MCP servers declared.</Muted>
      ) : (
        mcps.map((m) => {
          const r = rec(m);
          const id = str(r.id) ?? "mcp";
          const missing = mcpMissingSecrets(m, ctx.setKeys);
          return (
            <JumpRow
              key={id}
              icon={<HardDrivesIcon {...ICON} />}
              title={id}
              subtitle={str(r.connection) ? "shared connection" : str(r.url)}
              trailing={
                missing.length > 0 ? (
                  <WarnBadge title={`Needs: ${missing.join(", ")}`} />
                ) : undefined
              }
              onClick={() => ctx.onSelect(`cfg:mcp/${id}`)}
            />
          );
        })
      )}
      {canEdit ? (
        <Flex align="center" gap="2" className="mt-1" wrap="wrap">
          {(installations ?? []).length > 0 ? (
            <Select.Root
              value=""
              onValueChange={addFromConnection}
              disabled={applySpec.isPending}
            >
              <Select.Trigger
                placeholder="+ Add from a connection"
                className="min-w-[220px]"
              />
              <Select.Content>
                {(installations ?? []).map((i) => (
                  <Select.Item key={i.id} value={i.id}>
                    {i.display_name || i.url || i.id}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          ) : (
            <Muted>No connected MCP servers yet.</Muted>
          )}
          <Button
            size="1"
            variant="soft"
            onClick={() => setShowAdd(true)}
            disabled={connectCustomPending}
          >
            Connect new
          </Button>
        </Flex>
      ) : null}
      <AddCustomServerDialog
        open={showAdd}
        pending={connectCustomPending}
        onOpenChange={setShowAdd}
        onSubmit={(values) => {
          connectCustom(values);
          setShowAdd(false);
        }}
      />
    </Flex>
  );
}

function McpBody({
  mcp,
  spec,
  ctx,
}: {
  mcp: unknown;
  spec: AgentSpec;
  ctx: Ctx;
}) {
  const r = rec(mcp);
  const id = str(r.id) ?? "mcp";
  const tools = arr(r.tools);
  const missing = mcpMissingSecrets(mcp, ctx.setKeys);
  const provider = mcpProvider(mcp);
  const connection = str(r.connection);
  const providers = identityProviders(spec);
  // `spec.mcps[].kind` is the authoritative, explicit credential model.
  // Fall back to inferring from the credential fields for any legacy entry
  // written before `kind` was required.
  const declaredKind = str(r.kind);
  const authMode: "agent" | "principal" =
    declaredKind === "agent" || declaredKind === "principal"
      ? declaredKind
      : connection
        ? "agent"
        : "principal";
  // Whether the chosen `auth.provider` is actually declared in
  // `spec.identity_providers[]` — drives the preview card's status/badge.
  const identityDeclared =
    !!provider && providers.some((p) => providerId(p) === provider);

  const {
    installations,
    installationsLoading,
    connectCustom,
    connectCustomPending,
  } = useMcpConnect();
  const applySpec = useApplyAgentSpec(ctx.idOrSlug, ctx.applicationId);
  const [showAdd, setShowAdd] = useState(false);
  const canEdit = !!ctx.revisionState;
  const saving = applySpec.isPending;

  // Live tool catalog for an agent-level shared connection — the connection id
  // IS the mcp_store installation id, so we can list its tools and show a
  // per-tool permission against each. A principal-level (auth.provider) MCP has
  // no installation here, so `connection` is null and this stays empty.
  const { tools: catalogTools, isLoading: catalogLoading } =
    useMcpInstallationTools(connection ?? null, { autoRefreshIfEmpty: true });
  // Per-agent override level keyed by remote tool name, plus the connection-wide
  // default. Effective level per tool = override ?? default.
  const overrides = toolLevelOverrides(r);
  const defaultLevel = toToolApprovalLevel(r.default_tool_approval);
  const effectiveDefault = defaultLevel ?? DEFAULT_TOOL_APPROVAL;
  // Project the live catalog into the shared list's vocabulary: each tool's
  // displayed state is its override (if any) resolved against the default. The
  // panel is permission-agnostic, so the override/default math stays here.
  const displayTools: McpInstallationTool[] = catalogTools.map((t) => ({
    ...t,
    approval_state:
      LEVEL_TO_APPROVAL[overrides.get(t.tool_name) ?? effectiveDefault],
  }));

  // Rebuild the full spec with this mcps[] entry transformed, then draft-branch
  // (if needed) + PATCH. Lands on (and selects) a new draft off a non-draft.
  // Destructure the ctx fields the callback reads so the dep array is stable —
  // `ctx` is a fresh object literal on every parent render, which would
  // otherwise change identity each time and defeat the useCallback memoization.
  const { revisionId, revisionState, onSelectRevision } = ctx;
  const apply = useCallback(
    (mutate: (entry: Record<string, unknown>) => Record<string, unknown>) => {
      if (!revisionState) return;
      const nextMcps = arr(spec.mcps).map((m) =>
        (str(rec(m).id) ?? "mcp") === id ? mutate(rec(m)) : m,
      );
      applySpec.mutate(
        {
          revision: { id: revisionId, state: revisionState },
          spec: { ...spec, mcps: nextMcps },
        },
        {
          onSuccess: (rev) => {
            if (rev.id !== revisionId) onSelectRevision?.(rev.id);
          },
          onError: (e) => toast.error(e.message || "Failed to save"),
        },
      );
    },
    [applySpec, revisionId, revisionState, onSelectRevision, id, spec],
  );

  const setConnection = (value: string) => {
    if (value === "none") {
      apply((entry) => {
        const next: Record<string, unknown> = { ...entry, kind: "agent" };
        delete next.connection;
        return next;
      });
      return;
    }
    const install = (installations ?? []).find((i) => i.id === value);
    apply((entry) => ({
      ...entry,
      kind: "agent",
      connection: value,
      url: install?.url ?? entry.url,
    }));
  };

  // Switch the credential model. The two are mutually exclusive (enforced by
  // the spec schema), so flipping clears the other side: → agent drops the
  // per-asker identity (pick a connection next); → principal drops the shared
  // connection and wires an identity provider (defaults to the current one,
  // else the first declared).
  const setAuthMode = (next: "agent" | "principal") => {
    if (next === "agent") {
      apply((entry) => {
        const n: Record<string, unknown> = { ...entry, kind: "agent" };
        delete n.auth;
        return n;
      });
      return;
    }
    const fallback =
      provider ?? (providers[0] ? providerId(providers[0]) : undefined);
    apply((entry) => {
      const n: Record<string, unknown> = { ...entry, kind: "principal" };
      delete n.connection;
      if (fallback) n.auth = { ...rec(entry.auth), provider: fallback };
      return n;
    });
  };

  const setIdentityProvider = (value: string) => {
    apply((entry) => ({
      ...entry,
      kind: "principal",
      auth: { ...rec(entry.auth), provider: value },
    }));
  };

  const setToolApproval = (toolName: string, requiresApproval: boolean) => {
    apply((entry) => ({
      ...entry,
      tools: arr(entry.tools).map((t) => {
        const name = typeof t === "string" ? t : (str(rec(t).name) ?? "");
        if (name !== toolName) return t;
        const base = typeof t === "object" ? rec(t) : {};
        return { ...base, name, requires_approval: requiresApproval };
      }),
    }));
  };

  // Set the connection-wide default permission (allow / approve / deny). Setting
  // it activates the per-agent model on this entry (the runner stops treating
  // tools[] as a legacy allowlist).
  const setDefaultLevel = (level: ToolApprovalLevel) => {
    apply((entry) => ({ ...entry, default_tool_approval: level }));
  };

  // Override one tool's permission. Dropping it back to the connection default
  // removes the override so the spec stays minimal (no entry ⇒ inherits default).
  const setToolLevel = (toolName: string, level: ToolApprovalLevel) => {
    apply((entry) => {
      const others = arr(entry.tools).filter(
        (t) => (typeof t === "string" ? t : str(rec(t).name)) !== toolName,
      );
      const tools =
        level === effectiveDefault
          ? others
          : [...others, { name: toolName, level }];
      return {
        ...entry,
        default_tool_approval: entry.default_tool_approval ?? effectiveDefault,
        tools,
      };
    });
  };

  // Drop this whole mcps[] entry from the spec and return to the list. The
  // shared connection (the mcp_store installation) is untouched — only the
  // agent's reference to it goes away.
  const removeMcp = () => {
    if (!revisionState) return;
    const nextMcps = arr(spec.mcps).filter(
      (m) => (str(rec(m).id) ?? "mcp") !== id,
    );
    applySpec.mutate(
      {
        revision: { id: revisionId, state: revisionState },
        spec: { ...spec, mcps: nextMcps },
      },
      {
        onSuccess: (rev) => {
          if (rev.id !== revisionId) onSelectRevision?.(rev.id);
          ctx.onSelect("cfg:mcps");
        },
        onError: (e) => toast.error(e.message || "Failed to remove MCP server"),
      },
    );
  };

  const connectionMissing =
    !!connection && !(installations ?? []).some((i) => i.id === connection);

  return (
    <Flex direction="column" gap="3">
      <Flex align="center" justify="between" gap="2">
        <Select.Root
          value={authMode}
          onValueChange={(v) => setAuthMode(v as "agent" | "principal")}
          disabled={!canEdit || saving}
        >
          <Select.Trigger className="min-w-60" />
          <Select.Content>
            <Select.Item value="agent">
              Agent-level — shared credential
            </Select.Item>
            <Select.Item value="principal">
              Principal-level — per-asker identity
            </Select.Item>
          </Select.Content>
        </Select.Root>
        {canEdit ? (
          <Button
            size="1"
            variant="soft"
            color="red"
            onClick={removeMcp}
            disabled={saving}
          >
            <TrashIcon size={12} />
            Remove server
          </Button>
        ) : null}
      </Flex>
      <Muted>
        {authMode === "agent"
          ? "One shared credential every asker reuses — an OAuth/API-key connection, or a bring-your-own token."
          : "Each asker acts as themselves through a linked identity provider."}
      </Muted>

      {authMode === "agent" ? (
        <div>
          <Subhead>Connection</Subhead>
          <Muted>
            One shared credential an owner connects once (OAuth or API key) and
            every asker reuses — askers never sign in. Leave unset to bring your
            own token via secrets + headers.
          </Muted>
          <Flex align="center" gap="2" className="mt-1.5">
            <Select.Root
              value={connection ?? "none"}
              onValueChange={setConnection}
              disabled={!canEdit || saving || installationsLoading}
            >
              <Select.Trigger
                placeholder="No connection"
                className="min-w-[220px]"
              />
              <Select.Content>
                <Select.Item value="none">No connection</Select.Item>
                {(installations ?? []).map((i) => (
                  <Select.Item key={i.id} value={i.id}>
                    {i.display_name || i.url || i.id}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
            <Button
              size="1"
              variant="soft"
              onClick={() => setShowAdd(true)}
              disabled={connectCustomPending}
            >
              Connect new
            </Button>
          </Flex>
          {connectionMissing ? (
            <Text className="mt-1 block text-[12px] text-amber-11">
              Referenced connection isn't in this project — reconnect it or pick
              another.
            </Text>
          ) : null}
        </div>
      ) : (
        <div>
          <Subhead>Acts as identity</Subhead>
          <Muted>
            Each asker connects as themselves through this identity provider —
            required for principal-level. Manage providers in the identities
            section.
          </Muted>
          {providers.length > 0 ? (
            <Flex direction="column" gap="2" className="mt-1.5">
              <Select.Root
                value={provider}
                onValueChange={setIdentityProvider}
                disabled={!canEdit || saving}
              >
                <Select.Trigger
                  placeholder="Choose an identity"
                  className="min-w-60"
                />
                <Select.Content>
                  {providers.map((p) => {
                    const pid = providerId(p);
                    return (
                      <Select.Item key={pid} value={pid}>
                        <Flex align="center" gap="2">
                          <FingerprintIcon {...ICON} />
                          {pid}
                        </Flex>
                      </Select.Item>
                    );
                  })}
                </Select.Content>
              </Select.Root>
              {provider ? (
                <JumpRow
                  icon={<FingerprintIcon {...ICON} />}
                  title={provider}
                  mono
                  subtitle={
                    identityDeclared
                      ? "per-asker linked identity — each asker connects as themselves"
                      : "not declared in identities"
                  }
                  trailing={
                    identityDeclared ? undefined : (
                      <Badge color="amber">undeclared</Badge>
                    )
                  }
                  onClick={() => ctx.onSelect(`cfg:identity/${provider}`)}
                />
              ) : (
                <Text className="block text-[12px] text-amber-11">
                  Principal-level needs a linked identity — choose one above.
                </Text>
              )}
            </Flex>
          ) : (
            <Attention>
              <Text className="text-[12px] text-gray-12">
                No identity providers declared. Add one in the identities
                section to use principal-level auth.
              </Text>
              <Flex className="mt-1.5">
                <Button
                  size="1"
                  variant="soft"
                  color="amber"
                  onClick={() => ctx.onSelect("cfg:identities")}
                >
                  Manage identities
                </Button>
              </Flex>
            </Attention>
          )}
        </div>
      )}

      <AddCustomServerDialog
        open={showAdd}
        pending={connectCustomPending}
        onOpenChange={setShowAdd}
        onSubmit={(values) => {
          connectCustom(values);
          setShowAdd(false);
        }}
      />

      {str(r.url) ? (
        <Row label="url" value={str(r.url) as string} mono />
      ) : null}
      {!connection && missing.length > 0 ? (
        <Attention>
          <Text className="text-[12px] text-gray-12">
            Missing secret{missing.length > 1 ? "s" : ""}:
          </Text>
          <Flex gap="1.5" wrap="wrap" className="mt-1.5">
            {missing.map((key) => (
              <Button
                key={key}
                size="1"
                variant="soft"
                color="amber"
                onClick={() => ctx.onSelect(`cfg:secret/${key}`)}
              >
                Set {key}
              </Button>
            ))}
          </Flex>
        </Attention>
      ) : null}

      {connection ? (
        <div>
          <Subhead>Tool permissions</Subhead>
          <Muted>
            The default applies to every tool this server exposes; override
            individual tools below. Allow = runs automatically · Approve = asks
            the approver each call · Deny = hidden from the agent.
          </Muted>
          <Attention>
            <Text className="text-[12px] text-gray-12">
              These settings govern this agent. The connection owner's approval
              marks are informational — they aren't enforced for this agent.
            </Text>
          </Attention>
          <div className="mt-2">
            <ToolPermissionList
              tools={displayTools}
              isLoading={catalogLoading}
              disabled={!canEdit || saving}
              defaultControl={{
                value: LEVEL_TO_APPROVAL[effectiveDefault],
                onChange: (v) => setDefaultLevel(APPROVAL_TO_LEVEL[v]),
              }}
              onSetTool={(name, state) =>
                setToolLevel(name, APPROVAL_TO_LEVEL[state])
              }
              emptyTitle="No tools discovered yet."
              emptyHint="They appear once the connection is verified."
            />
          </div>
        </div>
      ) : (
        <div>
          <Subhead>Tools · {tools.length}</Subhead>
          {tools.length === 0 ? (
            <Muted>No tools selected from this server.</Muted>
          ) : (
            <Flex direction="column" gap="1.5" className="mt-1">
              {tools.map((t) => {
                const name =
                  typeof t === "string" ? t : (str(rec(t).name) ?? "tool");
                const requiresApproval =
                  typeof t === "object" && rec(t).requires_approval === true;
                return (
                  <Flex
                    key={name}
                    align="center"
                    gap="2"
                    className="rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-3 py-2"
                  >
                    <Text className="min-w-0 flex-1 truncate text-[12px] text-gray-12 [font-family:var(--font-mono)]">
                      {name}
                    </Text>
                    <Text className="text-[11px] text-gray-10">
                      Requires approval
                    </Text>
                    <Switch
                      size="1"
                      checked={requiresApproval}
                      onCheckedChange={(v) => setToolApproval(name, v === true)}
                      disabled={!canEdit || saving}
                    />
                  </Flex>
                );
              })}
            </Flex>
          )}
        </div>
      )}
    </Flex>
  );
}

function providerSummary(p: unknown, used: number): string {
  const r = rec(p);
  const binding = str(r.binding) === "agent" ? "shared (agent)" : "per-asker";
  const parts = [str(r.kind), binding].filter(Boolean) as string[];
  parts.push(used === 0 ? "unused" : `${used} consumer${used > 1 ? "s" : ""}`);
  return parts.join(" · ");
}

// Both identity components apply a full-spec PATCH the same way — same mutation,
// same success (auto-jump to a newly branched draft) and error handling — so
// share the wiring. The default error string is the only thing that differs.
function useSaveIdentitySpec(ctx: Ctx, defaultError: string) {
  const applySpec = useApplyAgentSpec(ctx.idOrSlug, ctx.applicationId);
  const saveSpec = (next: AgentSpec, onDone?: () => void) => {
    if (!ctx.revisionState) return;
    applySpec.mutate(
      {
        revision: { id: ctx.revisionId, state: ctx.revisionState },
        spec: next,
      },
      {
        onSuccess: (rev) => {
          if (rev.id !== ctx.revisionId) ctx.onSelectRevision?.(rev.id);
          onDone?.();
        },
        onError: (e) => toast.error(e.message || defaultError),
      },
    );
  };
  return { saveSpec, saving: applySpec.isPending };
}

function IdentitiesOverview({ spec, ctx }: { spec: AgentSpec; ctx: Ctx }) {
  const providers = identityProviders(spec);
  const { saveSpec, saving } = useSaveIdentitySpec(
    ctx,
    "Failed to save identity providers",
  );
  const canEdit = !!ctx.revisionState;
  const authoritative = authoritativeProviderId(spec);
  const [showOauth, setShowOauth] = useState(false);
  const hasPosthog = providers.some((p) => str(rec(p).kind) === "posthog");

  // The PATCH replaces `spec` wholesale, so omit the key to clear it.
  const setAuthoritative = (value: string) => {
    const next: AgentSpec = { ...spec };
    if (value && value !== NONE_PROVIDER) next.authoritative_provider = value;
    else delete next.authoritative_provider;
    saveSpec(next);
  };

  const addPosthog = () => {
    if (hasPosthog) return;
    saveSpec(
      {
        ...spec,
        identity_providers: [
          ...providers,
          { kind: "posthog", id: "posthog", binding: "principal", scopes: [] },
        ],
      },
      () => ctx.onSelect("cfg:identity/posthog"),
    );
  };

  const addOauth2 = (entry: Record<string, unknown>) => {
    saveSpec({ ...spec, identity_providers: [...providers, entry] }, () => {
      setShowOauth(false);
      ctx.onSelect(`cfg:identity/${providerId(entry)}`);
    });
  };

  const authEntry = authoritative
    ? providers.find((p) => providerId(p) === authoritative)
    : undefined;
  const authInvalid =
    !!authoritative && (!authEntry || !establishesIdentity(authEntry));

  return (
    <Flex direction="column" gap="4">
      <div>
        <Subhead>Admission</Subhead>
        <Text className="mt-1 mb-2 block text-[12px] text-gray-10 leading-snug">
          Gate every session on a verified identity from one provider. When set,
          an unauthenticated Slack/HTTP request is handed an authorize link and
          no session runs until it resolves. Unset = the transport claim is the
          identity (passthrough / public).
        </Text>
        {canEdit ? (
          <Select.Root
            value={authoritative ?? NONE_PROVIDER}
            onValueChange={setAuthoritative}
            disabled={saving}
          >
            <Select.Trigger className="min-w-[260px]" />
            <Select.Content>
              <Select.Item value={NONE_PROVIDER}>
                None — transport identity
              </Select.Item>
              {providers.map((p) => {
                const id = providerId(p);
                const ok = establishesIdentity(p);
                return (
                  <Select.Item key={id} value={id} disabled={!ok}>
                    {id}
                    {ok ? "" : " — can't prove a subject"}
                  </Select.Item>
                );
              })}
            </Select.Content>
          </Select.Root>
        ) : (
          <Row
            label="authoritative"
            value={authoritative ?? "none (transport identity)"}
            mono
          />
        )}
        {authInvalid ? (
          <Attention tone="warn">
            <Text className="text-[12px] text-gray-12">
              Authoritative provider{" "}
              <code className="[font-family:var(--font-mono)]">
                {authoritative}
              </code>{" "}
              {authEntry
                ? "can't prove a subject — use kind posthog, or oauth2 with a userinfo_url."
                : "isn't declared in identity_providers."}{" "}
              Admission will fail at runtime.
            </Text>
          </Attention>
        ) : null}
      </div>

      <div>
        <Subhead>Providers · {providers.length}</Subhead>
        {providers.length === 0 ? (
          <Muted>No identity providers declared.</Muted>
        ) : (
          <Flex direction="column" gap="2" className="mt-1.5">
            {providers.map((p) => {
              const id = providerId(p);
              const used = consumerCount(identityConsumers(spec, id));
              const isAuth = id === authoritative;
              return (
                <JumpRow
                  key={id}
                  icon={<FingerprintIcon {...ICON} />}
                  title={id}
                  mono
                  subtitle={providerSummary(p, used)}
                  trailing={
                    isAuth ? (
                      <Badge color="iris">authoritative</Badge>
                    ) : used === 0 ? (
                      <Badge color="amber">unused</Badge>
                    ) : undefined
                  }
                  onClick={() => ctx.onSelect(`cfg:identity/${id}`)}
                />
              );
            })}
          </Flex>
        )}
      </div>

      {canEdit ? (
        <Flex align="center" gap="2" wrap="wrap">
          {!hasPosthog ? (
            <Button
              size="1"
              variant="soft"
              onClick={addPosthog}
              disabled={saving}
            >
              Add PostHog identity
            </Button>
          ) : null}
          <Button
            size="1"
            variant="soft"
            onClick={() => setShowOauth((v) => !v)}
            disabled={saving}
          >
            {showOauth ? "Cancel" : "Add OAuth2 provider"}
          </Button>
        </Flex>
      ) : null}

      {showOauth && canEdit ? (
        <AddOauth2ProviderForm
          existingIds={providers.map((p) => providerId(p))}
          pending={saving}
          onAdd={addOauth2}
        />
      ) : null}
    </Flex>
  );
}

// userinfo_url is what lets an oauth2 provider be picked as authoritative.
// The form intentionally omits `client_secret`: it's a secret, so it lives in
// the agent's secret store (referenced by env-key via the top-level `secrets`
// list, not inlined on the provider entry) and is looked up server-side at
// token-exchange time. See posthog PR #66050 for the admission spec.
function AddOauth2ProviderForm({
  existingIds,
  pending,
  onAdd,
}: {
  existingIds: string[];
  pending: boolean;
  onAdd: (entry: Record<string, unknown>) => void;
}) {
  const [id, setId] = useState("");
  const [authorizeUrl, setAuthorizeUrl] = useState("");
  const [tokenUrl, setTokenUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [userinfoUrl, setUserinfoUrl] = useState("");
  const [scopes, setScopes] = useState("");

  const trimmedId = id.trim();
  const duplicate = existingIds.includes(trimmedId);
  const valid =
    !!trimmedId &&
    !duplicate &&
    !!authorizeUrl.trim() &&
    !!tokenUrl.trim() &&
    !!clientId.trim();

  const submit = () => {
    if (!valid) return;
    const entry: Record<string, unknown> = {
      kind: "oauth2",
      id: trimmedId,
      binding: "principal",
      authorize_url: authorizeUrl.trim(),
      token_url: tokenUrl.trim(),
      client_id: clientId.trim(),
      scopes: scopes
        .split(/[\s,]+/)
        .map((s) => s.trim())
        .filter(Boolean),
    };
    const ui = userinfoUrl.trim();
    if (ui) entry.userinfo_url = ui;
    onAdd(entry);
  };

  const field = (
    label: string,
    value: string,
    set: (v: string) => void,
    placeholder: string,
  ) => (
    <div className="flex flex-col gap-1">
      <Text className="text-[11px] text-gray-10 uppercase tracking-wide">
        {label}
      </Text>
      <TextField.Root
        value={value}
        onChange={(e) => set(e.target.value)}
        placeholder={placeholder}
        size="1"
      />
    </div>
  );

  return (
    <Flex
      direction="column"
      gap="2.5"
      className="rounded-(--radius-2) border border-border bg-(--gray-2) px-3 py-3"
    >
      {field("id", id, setId, "e.g. google")}
      {duplicate ? (
        <Text className="text-[11px] text-amber-11">
          A provider with this id already exists.
        </Text>
      ) : null}
      {field(
        "authorize url",
        authorizeUrl,
        setAuthorizeUrl,
        "https://accounts.google.com/o/oauth2/v2/auth",
      )}
      {field(
        "token url",
        tokenUrl,
        setTokenUrl,
        "https://oauth2.googleapis.com/token",
      )}
      {field("client id", clientId, setClientId, "the OAuth app client id")}
      {field(
        "userinfo url (required to be authoritative)",
        userinfoUrl,
        setUserinfoUrl,
        "https://openidconnect.googleapis.com/v1/userinfo",
      )}
      {field("scopes", scopes, setScopes, "space or comma separated")}
      <Flex justify="end">
        <Button
          size="1"
          variant="solid"
          onClick={submit}
          disabled={!valid || pending}
        >
          Add provider
        </Button>
      </Flex>
    </Flex>
  );
}

function IdentityBody({
  provider,
  id,
  spec,
  ctx,
}: {
  provider: unknown;
  id: string;
  spec: AgentSpec;
  ctx: Ctx;
}) {
  const r = rec(provider);
  const declared = provider != null;
  const kind = str(r.kind);
  const binding = str(r.binding) ?? "principal";
  const scopes = arr(r.scopes).filter(
    (s): s is string => typeof s === "string",
  );
  const consumers = identityConsumers(spec, id);
  const used = consumerCount(consumers);
  const authoritative = authoritativeProviderId(spec);
  const isAuth = declared && id === authoritative;
  const establishes = establishesIdentity(provider);
  const { saveSpec, saving } = useSaveIdentitySpec(
    ctx,
    "Failed to save identity provider",
  );
  const canEdit = !!ctx.revisionState;

  const setAuthoritative = (on: boolean) => {
    const next: AgentSpec = { ...spec };
    if (on) next.authoritative_provider = id;
    else delete next.authoritative_provider;
    saveSpec(next);
  };
  const removeProvider = () => {
    const next: AgentSpec = {
      ...spec,
      identity_providers: identityProviders(spec).filter(
        (p) => providerId(p) !== id,
      ),
    };
    if (authoritative === id) delete next.authoritative_provider;
    saveSpec(next, () => ctx.onSelect("cfg:identities"));
  };

  return (
    <Flex direction="column" gap="3">
      {!declared ? (
        <Attention tone="warn">
          <Text className="text-[12px] text-gray-12">
            A tool or MCP references identity{" "}
            <code className="[font-family:var(--font-mono)]">{id}</code>, but it
            isn't declared in <code>identity_providers</code>. Linking will fail
            at runtime.
          </Text>
        </Attention>
      ) : null}

      <Flex direction="column" gap="2">
        <Row label="id" value={id} mono />
        {kind ? <Row label="kind" value={kind} /> : null}
        <Row
          label="binding"
          value={
            binding === "agent"
              ? "agent — one shared link (not yet enforced)"
              : "principal — one link per asker"
          }
        />
        {str(r.authorize_url) ? (
          <Row
            label="authorize url"
            value={str(r.authorize_url) as string}
            mono
          />
        ) : null}
        {str(r.client_id) ? (
          <Row label="client id" value={str(r.client_id) as string} mono />
        ) : null}
      </Flex>

      {declared ? (
        <div>
          <Subhead>Admission</Subhead>
          {isAuth ? (
            <Attention>
              <Text className="text-[12px] text-gray-12">
                Authoritative provider — every session must resolve a verified
                identity here before it runs.
              </Text>
            </Attention>
          ) : (
            <Muted>
              {establishes
                ? "Make this the authoritative provider to gate every session on it."
                : "Can't be authoritative — it doesn't prove a subject (needs kind posthog, or oauth2 with a userinfo_url)."}
            </Muted>
          )}
          {canEdit ? (
            <Flex gap="2" className="mt-2" wrap="wrap">
              {isAuth ? (
                <Button
                  size="1"
                  variant="soft"
                  onClick={() => setAuthoritative(false)}
                  disabled={saving}
                >
                  Clear authoritative
                </Button>
              ) : (
                <Button
                  size="1"
                  variant="soft"
                  onClick={() => setAuthoritative(true)}
                  disabled={saving || !establishes}
                >
                  Make authoritative
                </Button>
              )}
            </Flex>
          ) : null}
        </div>
      ) : null}

      {scopes.length > 0 ? (
        <div>
          <Subhead>Scopes</Subhead>
          <Flex gap="1.5" wrap="wrap" className="mt-1.5">
            {scopes.map((s) => (
              <Badge key={s} color="gray">
                {s}
              </Badge>
            ))}
          </Flex>
        </div>
      ) : null}

      <div>
        <Subhead>Used by · {used}</Subhead>
        {used === 0 ? (
          <Muted>No custom tool or MCP server declares this provider.</Muted>
        ) : (
          <Flex direction="column" gap="1.5" className="mt-1">
            {consumers.tools.map((tid) => (
              <JumpRow
                key={`tool:${tid}`}
                icon={<WrenchIcon {...ICON} />}
                title={shortName(tid)}
                subtitle="custom tool"
                onClick={() => ctx.onSelect(`cfg:tool/${tid}`)}
              />
            ))}
            {consumers.mcps.map((mid) => (
              <JumpRow
                key={`mcp:${mid}`}
                icon={<HardDrivesIcon {...ICON} />}
                title={mid}
                subtitle="MCP server"
                onClick={() => ctx.onSelect(`cfg:mcp/${mid}`)}
              />
            ))}
          </Flex>
        )}
        <Text className="mt-2 block text-[11px] text-gray-10 leading-snug">
          Native{" "}
          <span className="[font-family:var(--font-mono)]">@posthog/*</span>{" "}
          tools declare their provider intrinsically and aren't listed here.
        </Text>
      </div>

      {canEdit && declared ? (
        <Flex justify="end">
          <Button
            size="1"
            variant="soft"
            onClick={removeProvider}
            disabled={saving}
          >
            <TrashIcon size={13} /> Remove provider
          </Button>
        </Flex>
      ) : null}
    </Flex>
  );
}

function SecretsOverview({ spec, ctx }: { spec: AgentSpec; ctx: Ctx }) {
  const keys = allSecretKeys(spec, ctx.setKeys);
  if (keys.length === 0) return <Muted>No secrets declared.</Muted>;
  return (
    <Flex direction="column" gap="3">
      <Muted>Env keys this agent reads. Values are never shown.</Muted>
      <Flex direction="column" gap="2">
        {keys.map((key) => (
          <JumpRow
            key={key}
            icon={<KeyIcon {...ICON} />}
            title={key}
            mono
            trailing={
              ctx.setKeys.includes(key) ? (
                <Badge color="green">set</Badge>
              ) : (
                <Badge color="amber">not set</Badge>
              )
            }
            onClick={() => ctx.onSelect(`cfg:secret/${key}`)}
          />
        ))}
      </Flex>
    </Flex>
  );
}

function SecretBody({
  keyName,
  setKeys,
  idOrSlug,
  revisionId,
}: {
  keyName: string;
  setKeys: string[];
  idOrSlug: string;
  revisionId: string;
}) {
  const isSet = setKeys.includes(keyName);
  return (
    <Flex direction="column" gap="2">
      <Row label="key" value={keyName} mono />
      <Row
        label="status"
        value={isSet ? "set" : "not set"}
        valueColor={isSet ? "var(--green-11)" : "var(--amber-11)"}
      />
      <SecretEditor
        idOrSlug={idOrSlug}
        revisionId={revisionId}
        keyName={keyName}
        isSet={isSet}
      />
    </Flex>
  );
}

interface EditableBundle {
  idOrSlug: string;
  revisionId: string;
  /** Canonical bundle path written through the per-file PUT endpoint. */
  path: string;
}

function BundleFileBody({
  file,
  emptyLabel = "Not in the loaded bundle.",
  editable,
}: {
  file: BundleFile | undefined;
  emptyLabel?: string;
  editable?: EditableBundle;
}) {
  if (editable) {
    return (
      <EditableMarkdownBody
        // Remount when the user picks a different file so we start fresh
        // instead of carrying draft/edit state across paths via an effect.
        key={editable.path}
        file={file}
        emptyLabel={emptyLabel}
        editable={editable}
      />
    );
  }
  if (!file) return <Muted>{emptyLabel}</Muted>;
  if (file.language === "markdown") {
    return (
      <div className="text-[13px]">
        <MarkdownRenderer content={file.content} />
      </div>
    );
  }
  return <CodeBlock>{file.content}</CodeBlock>;
}

/**
 * Edit/view toggle backed by the per-file PUT endpoint. Used for `agent.md`
 * and `skills/<id>/SKILL.md` on draft revisions. Tool source / schema stay on
 * the read-only branch above. When `file` is undefined (e.g. a skill scaffold
 * with no body yet) we still let the user write fresh content for `path`.
 */
function EditableMarkdownBody({
  file,
  emptyLabel,
  editable,
}: {
  file: BundleFile | undefined;
  emptyLabel: string;
  editable: EditableBundle;
}) {
  const initial = file?.content ?? "";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(initial);
  const [syncedInitial, setSyncedInitial] = useState(initial);
  const mutation = useUpdateAgentDraftBundleFile(
    editable.idOrSlug,
    editable.revisionId,
  );

  // Pull in upstream content changes (initial bundle load, post-save refetch)
  // during render rather than via an effect, but only while the user isn't
  // actively editing — otherwise an unrelated refetch (e.g. a concurrent bulk
  // import) would silently wipe their draft. File-switch resets are handled by
  // `key={editable.path}` at the call site.
  if (initial !== syncedInitial && !editing) {
    setSyncedInitial(initial);
    setDraft(initial);
  }

  if (!editing) {
    return (
      <Flex direction="column" gap="2">
        <Flex justify="end">
          <Button
            size="1"
            variant="soft"
            color="gray"
            onClick={() => setEditing(true)}
          >
            Edit
          </Button>
        </Flex>
        {file ? (
          <div className="text-[13px]">
            <MarkdownRenderer content={file.content} />
          </div>
        ) : (
          <Muted>{emptyLabel}</Muted>
        )}
      </Flex>
    );
  }

  return (
    <Flex direction="column" gap="2">
      <textarea
        aria-label={editable.path}
        value={draft}
        onChange={(e) => setDraft(e.currentTarget.value)}
        disabled={mutation.isPending}
        spellCheck={false}
        className="min-h-[280px] w-full resize-y rounded-(--radius-2) border border-border bg-(--color-panel-solid) p-3 text-[12.5px] text-gray-12 [font-family:var(--font-mono)] focus:border-(--accent-7) focus:outline-none"
      />
      {mutation.isError ? (
        <Text className="text-(--red-11) text-[12px]">
          {mutation.error?.message ?? "Save failed"}
        </Text>
      ) : null}
      <Flex justify="end" gap="2">
        <Button
          size="1"
          variant="soft"
          color="gray"
          disabled={mutation.isPending}
          onClick={() => {
            setDraft(initial);
            setEditing(false);
            mutation.reset();
          }}
        >
          Cancel
        </Button>
        <Button
          size="1"
          loading={mutation.isPending}
          disabled={draft === initial}
          onClick={() =>
            mutation.mutate(
              { path: editable.path, content: draft },
              { onSuccess: () => setEditing(false) },
            )
          }
        >
          Save
        </Button>
      </Flex>
    </Flex>
  );
}

function Row({
  label,
  value,
  mono,
  valueColor,
}: {
  label: string;
  value: string;
  mono?: boolean;
  valueColor?: string;
}) {
  return (
    <Flex
      align="center"
      justify="between"
      gap="3"
      className="rounded-(--radius-2) border border-border bg-(--gray-2) px-3 py-2"
    >
      <Text className="shrink-0 text-[11px] text-gray-10 uppercase tracking-wide">
        {label}
      </Text>
      <Text
        className={`truncate text-[12.5px] text-gray-12 ${mono ? "[font-family:var(--font-mono)]" : ""}`}
        style={valueColor ? { color: valueColor } : undefined}
      >
        {value}
      </Text>
    </Flex>
  );
}

function JumpRow({
  icon,
  title,
  subtitle,
  trailing,
  mono,
  onClick,
}: {
  icon: ReactNode;
  title: string;
  subtitle?: string;
  trailing?: ReactNode;
  mono?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-3 py-2.5 text-left hover:border-(--gray-7)"
    >
      {icon}
      <Flex direction="column" gap="0.5" className="min-w-0 flex-1">
        <Text
          className={`truncate text-[12.5px] text-gray-12 ${mono ? "[font-family:var(--font-mono)]" : ""}`}
        >
          {title}
        </Text>
        {subtitle ? (
          <Text className="truncate text-[11px] text-gray-10">{subtitle}</Text>
        ) : null}
      </Flex>
      {trailing ? <span className="shrink-0">{trailing}</span> : null}
    </button>
  );
}

function Attention({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "warn";
}) {
  return (
    <div
      className={`rounded-(--radius-2) border px-3 py-2 ${
        tone === "warn"
          ? "border-(--amber-6) bg-(--amber-3)"
          : "border-(--amber-6) bg-(--amber-2)"
      }`}
    >
      {children}
    </div>
  );
}

function Subhead({ children }: { children: ReactNode }) {
  return (
    <Text className="block text-[11px] text-gray-10 uppercase tracking-wide [font-family:var(--font-mono)]">
      {children}
    </Text>
  );
}

function Muted({ children }: { children: ReactNode }) {
  return (
    <Text className="text-[12px] text-gray-10 leading-snug">{children}</Text>
  );
}
