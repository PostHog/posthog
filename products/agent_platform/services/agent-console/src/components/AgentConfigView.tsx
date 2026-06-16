/**
 * `<AgentConfigView />` — the live configuration surface.
 *
 * A thin `<RevisionBar>` (pick a revision, run lifecycle actions) above the
 * `<AgentConfigExplorer>` (the whole spec + bundle as one filesystem). This
 * replaces the old `RevisionsBrowser` split view and absorbs the connections
 * surface: secrets, integrations, MCPs, and Slack setup all live in the
 * explorer now.
 *
 * Data wiring this host owns (the explorer stays presentational):
 *   - bundle files     → `getBundle`
 *   - set-secret status → `listEnvKeys`
 *   - secret editor     → `<SecretEditDialog>` driven by `?edit_secret=`
 *   - lifecycle actions → `freeze` / `promote` / `archive` + confirm
 *   - Slack setup       → `<SlackSetupCard>` injected under the slack trigger
 */

'use client'

import { useMemo, useState } from 'react'

import type { AgentApplicationFixture, AgentRevisionFixture } from '@posthog/agent-chat/fixtures'

import { useAgentIngressFallbackBaseUrl, useSessionTeamId } from '@/components/session-context'
import {
    ApiError,
    archiveRevision,
    fireCron,
    freezeRevision,
    getBundle,
    listEnvKeys,
    promoteRevision,
} from '@/lib/apiClient'
import { getTriggerRequiredSecrets } from '@/lib/triggerSecrets'
import { useResource } from '@/lib/useResource'

import { AgentConfigExplorer } from './AgentConfigExplorer'
import { ConfirmDialog } from './ConfirmDialog'
import { dialogCopy, type LifecycleAction } from './revision-helpers'
import { RevisionBar } from './RevisionBar'
import { SecretAddDialog } from './SecretAddDialog'
import { SecretEditDialog } from './SecretEditDialog'
import { SlackSetupCard } from './SlackSetupCard'

export interface AgentConfigViewProps {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    selectedRevisionId: string | null
    onSelectRevision: (id: string) => void
    /** Explorer selection — a node path, persisted as `?node=`. */
    selectedNode: string | null
    onSelectNode: (path: string) => void
    /** Open secret editor key (driven by `?edit_secret=`). */
    editingSecret: string | null
    /** Chat session waiting on a secret (driven by `?callback_session=`). */
    callbackSessionId: string | null
    onChangeEditingSecret: (key: string | null) => void
    /** Refetch agent + revisions after a lifecycle action or secret change. */
    onMutated: () => void
    onTryDraft?: (revisionId: string) => void
    /** Navigate to a session — used to jump to the session a manual cron fire creates. */
    onOpenSession?: (sessionId: string) => void
    /** Refresh control rendered in the revision bar. */
    refreshSlot?: React.ReactNode
}

interface PendingAction {
    action: LifecycleAction
    revision: AgentRevisionFixture
}

/** The lifecycle confirm — `dialogCopy` is computed once here. */
function LifecycleConfirm({
    pending,
    agent,
    running,
    error,
    onConfirm,
    onClose,
}: {
    pending: PendingAction
    agent: AgentApplicationFixture
    running: boolean
    error: string | null
    onConfirm: () => void
    onClose: () => void
}): React.ReactElement {
    const copy = dialogCopy(pending, agent)
    return (
        <ConfirmDialog
            open
            onOpenChange={(open) => {
                if (!open) {
                    onClose()
                }
            }}
            title={copy.title}
            description={copy.description}
            confirmLabel={copy.confirmLabel}
            confirmVariant={pending.action === 'archive' ? 'destructive' : 'default'}
            running={running}
            error={error}
            onConfirm={onConfirm}
        />
    )
}

export function AgentConfigView({
    agent,
    revisions,
    selectedRevisionId,
    onSelectRevision,
    selectedNode,
    onSelectNode,
    editingSecret,
    callbackSessionId,
    onChangeEditingSecret,
    onMutated,
    onTryDraft,
    onOpenSession,
    refreshSlot,
}: AgentConfigViewProps): React.ReactElement {
    // SessionGate (in AppShell) blocks rendering until teamId resolves.
    const teamId = useSessionTeamId()!
    // Django's ingress_base_url is canonical; the console-config fallback
    // covers local dev where Django has no AGENT_INGRESS_PUBLIC_URL.
    const fallbackIngressBase = useAgentIngressFallbackBaseUrl(agent.slug)

    const sortedRevisions = useMemo(
        () => [...revisions].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()),
        [revisions]
    )
    const selected = revisions.find((r) => r.id === selectedRevisionId) ?? sortedRevisions[0] ?? null

    // env_keys are refetched after every secret save / clear so set/unset
    // status in the explorer stays accurate without a full reload.
    const [secretReload, setSecretReload] = useState(0)
    const envKeysRes = useResource(
        () => (selected ? listEnvKeys(teamId, agent.slug).catch(() => [] as string[]) : Promise.resolve([])),
        [teamId, agent.slug, secretReload]
    )
    const setSecrets = envKeysRes.data ?? []
    const bumpSecrets = (): void => setSecretReload((n) => n + 1)

    const bundleRes = useResource(
        () => (selected ? getBundle(teamId, agent.slug, selected.id) : Promise.resolve([])),
        [teamId, agent.slug, selected?.id ?? '']
    )
    const bundle = bundleRes.data ?? []

    // Lifecycle confirm + run.
    const [pending, setPending] = useState<PendingAction | null>(null)
    const [running, setRunning] = useState(false)
    const [actionError, setActionError] = useState<string | null>(null)
    const requestAction = (action: LifecycleAction, revision: AgentRevisionFixture): void => {
        setActionError(null)
        setPending({ action, revision })
    }
    const closeDialog = (): void => {
        if (!running) {
            setPending(null)
            setActionError(null)
        }
    }
    const runAction = async (): Promise<void> => {
        if (!pending) {
            return
        }
        setRunning(true)
        setActionError(null)
        const fn =
            pending.action === 'freeze'
                ? freezeRevision
                : pending.action === 'promote'
                  ? promoteRevision
                  : archiveRevision
        try {
            await fn(teamId, agent.slug, pending.revision.id)
            setPending(null)
            onMutated()
        } catch (err) {
            setActionError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err))
        } finally {
            setRunning(false)
        }
    }

    // Add-custom-secret: capture the name, then open the editor for it.
    const [addingSecret, setAddingSecret] = useState(false)

    const spec = useMemo(() => (selected?.spec ?? {}) as Record<string, unknown>, [selected])
    const declaredSecrets = useMemo(() => {
        // spec.secrets[] entries are either bare strings (back-compat) or
        // {name, allowed_hosts: string[]}; collect the names from either form.
        const set = new Set<string>()
        if (Array.isArray(spec.secrets)) {
            for (const entry of spec.secrets) {
                if (typeof entry === 'string') {
                    set.add(entry)
                } else if (
                    entry &&
                    typeof entry === 'object' &&
                    typeof (entry as { name?: unknown }).name === 'string'
                ) {
                    set.add((entry as { name: string }).name)
                }
            }
        }
        for (const req of getTriggerRequiredSecrets(spec)) {
            set.add(req.key)
        }
        return set
    }, [spec])
    const hasSlackTrigger = useMemo(
        () =>
            Array.isArray(spec.triggers) &&
            (spec.triggers as Array<{ type?: string }>).some((t) => t?.type === 'slack'),
        [spec]
    )

    if (!selected) {
        return (
            <p className="rounded-md border border-dashed border-border px-4 py-3 text-sm text-muted-foreground">
                This agent has no revisions yet.
            </p>
        )
    }

    return (
        <div className="flex h-full min-h-0 flex-col gap-3">
            <RevisionBar
                agent={agent}
                revisions={revisions}
                selectedRevisionId={selected.id}
                onSelectRevision={onSelectRevision}
                onAction={requestAction}
                onTryDraft={onTryDraft}
                refreshSlot={refreshSlot}
            />

            <div className="min-h-0 flex-1">
                <AgentConfigExplorer
                    spec={spec}
                    files={bundle}
                    setSecrets={setSecrets}
                    onEditSecret={(key) => onChangeEditingSecret(key)}
                    onAddCustomSecret={() => setAddingSecret(true)}
                    slackSetup={
                        hasSlackTrigger ? (
                            <SlackSetupCard teamId={teamId} agentSlug={agent.slug} revisionId={selected.id} />
                        ) : undefined
                    }
                    onFireCron={async (cronName) => {
                        const res = await fireCron(teamId, agent.slug, selected.id, cronName)
                        // Jump straight to the session the firing created so the
                        // author can watch the run they just kicked off.
                        onOpenSession?.(res.session_id)
                        return res
                    }}
                    selectedPath={selectedNode}
                    onSelectPath={onSelectNode}
                    agentSlug={agent.slug}
                    ingressBaseUrl={agent.ingress_base_url ?? fallbackIngressBase ?? undefined}
                    height="100%"
                />
            </div>

            <SecretEditDialog
                agentSlug={agent.slug}
                secret={editingSecret}
                callbackSessionId={callbackSessionId}
                isDeclaredOnSpec={editingSecret ? declaredSecrets.has(editingSecret) : true}
                onClose={() => onChangeEditingSecret(null)}
                onMutated={bumpSecrets}
            />
            <SecretAddDialog
                open={addingSecret}
                onCancel={() => setAddingSecret(false)}
                onConfirm={(name) => {
                    setAddingSecret(false)
                    onChangeEditingSecret(name)
                }}
            />
            {pending ? (
                <LifecycleConfirm
                    pending={pending}
                    agent={agent}
                    running={running}
                    error={actionError}
                    onConfirm={runAction}
                    onClose={closeDialog}
                />
            ) : null}
        </div>
    )
}
