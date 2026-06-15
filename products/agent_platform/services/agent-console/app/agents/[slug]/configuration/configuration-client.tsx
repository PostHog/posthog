'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback } from 'react'

import { useAgent, useAgentReload, useRevisions } from '@/components/agent-context'
import { AgentConfigView } from '@/components/AgentConfigView'
import { useDockStore, useSetDockPage } from '@/components/dock-context'

export function ConfigurationSegment(): React.ReactElement {
    const agent = useAgent()
    const revisions = useRevisions()
    const reload = useAgentReload()
    const router = useRouter()
    const searchParams = useSearchParams()
    const { enterPlayground } = useDockStore()

    const explicitRevisionId = searchParams?.get('revision') ?? null
    const selectedRevisionId = explicitRevisionId ?? agent.live_revision ?? null

    // Explorer selection lives in `?node=`. Legacy `?section=` / `?file=`
    // (emitted by the concierge's focus tools) map onto a node so those
    // deep links keep landing somewhere sensible.
    const selectedNode = nodeFromParams(searchParams)

    const editingSecret = searchParams?.get('edit_secret') ?? null
    const callbackSessionId = searchParams?.get('callback_session') ?? null

    // Tell the concierge what's on screen — the section (and specific item)
    // currently open in the explorer — so it can talk about exactly that.
    useSetDockPage({
        kind: 'agent-config',
        agent: { id: agent.id, name: agent.name, slug: agent.slug },
        ...configViewFromNode(selectedNode),
    })

    // Single writer with a "what's changing" partial — each setter owns only
    // its key and merges into the current query string. `revision` collapses
    // to the URL default to keep the canonical link short. Writing `node`
    // clears the legacy section/file params so there's one source of truth.
    const pushParams = useCallback(
        (next: { revisionId?: string | null; node?: string | null; editSecret?: string | null }) => {
            const params = new URLSearchParams(searchParams?.toString() ?? '')
            if (next.revisionId !== undefined) {
                if (next.revisionId && next.revisionId !== agent.live_revision) {
                    params.set('revision', next.revisionId)
                } else {
                    params.delete('revision')
                }
            }
            if (next.node !== undefined) {
                params.delete('section')
                params.delete('file')
                if (next.node) {
                    params.set('node', next.node)
                } else {
                    params.delete('node')
                }
            }
            if (next.editSecret !== undefined) {
                if (next.editSecret) {
                    params.set('edit_secret', next.editSecret)
                } else {
                    params.delete('edit_secret')
                    params.delete('callback_session')
                }
            }
            const qs = params.toString()
            router.push(`/agents/${agent.slug}/configuration${qs ? `?${qs}` : ''}`, { scroll: false })
        },
        [agent.live_revision, agent.slug, router, searchParams]
    )

    const onTryDraft = useCallback(
        (revisionId: string) => {
            enterPlayground({ id: agent.id, slug: agent.slug, name: agent.name }, { previewRevisionId: revisionId })
        },
        [agent.id, agent.name, agent.slug, enterPlayground]
    )

    return (
        <div className="flex h-full flex-col px-6 pb-6 pt-4">
            <AgentConfigView
                agent={agent}
                revisions={revisions}
                selectedRevisionId={selectedRevisionId}
                onSelectRevision={(id) => pushParams({ revisionId: id })}
                selectedNode={selectedNode}
                onSelectNode={(node) => pushParams({ node })}
                editingSecret={editingSecret}
                callbackSessionId={callbackSessionId}
                onChangeEditingSecret={(key) => pushParams({ editSecret: key })}
                onMutated={reload}
                onTryDraft={onTryDraft}
            />
        </div>
    )
}

/** Resolve the explorer node from `?node=`, falling back to legacy params. */
function nodeFromParams(params: ReturnType<typeof useSearchParams>): string | null {
    const node = params?.get('node')
    if (node) {
        return node
    }
    const section = params?.get('section')
    if (section) {
        return `cfg:${section}`
    }
    const file = params?.get('file')
    if (file) {
        return nodeForFile(file)
    }
    return null
}

/**
 * Derive the dock page's `view` + `item` from the selected explorer node,
 * so the concierge envelope reflects what's on screen. Leaf paths
 * (`cfg:tool/<id>`) report both the area and the item; section paths
 * (`cfg:tools`) report just the area.
 */
function configViewFromNode(node: string | null): { view?: string; item?: string } {
    if (!node) {
        return {}
    }
    if (!node.startsWith('cfg:')) {
        return { view: 'file', item: node }
    }
    const [section, ...idParts] = node.slice('cfg:'.length).split('/')
    const id = idParts.join('/') || undefined
    // Leaf sections are singular — normalize to the area name the user sees.
    const area: Record<string, string> = {
        tool: 'tools',
        skill: 'skills',
        mcp: 'mcps',
        integration: 'integrations',
        secret: 'secrets',
        trigger: 'triggers',
    }
    const view = area[section] ?? section
    return id ? { view, item: id } : { view }
}

/** Map a bundle file path to the explorer node that renders it. */
function nodeForFile(path: string): string {
    if (path === 'agent.md') {
        return 'cfg:instructions'
    }
    const skill = path.match(/^skills\/([^/]+)\//)
    if (skill) {
        return `cfg:skill/${skill[1]}`
    }
    const tool = path.match(/^tools\/([^/]+)\//)
    if (tool) {
        return `cfg:tool/${tool[1]}`
    }
    return path
}
