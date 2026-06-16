// @ts-nocheck — registry feature is disabled (backend viewsets removed "pending a
// rethink"); its API types are `any`-stubbed in @/lib/registryApiTypes, which leaves
// implicit-any on the mappers below. Skip type-checking this dead page for now.
'use client'

import { notFound } from 'next/navigation'
import { use, useEffect, useState } from 'react'

import { useSessionTeamId } from '@/components/session-context'
import { getSkillTemplate, listSkillTemplateUsages, listSkillTemplateVersions } from '@/lib/registryClient'
import type { SkillTemplateDetail } from '@/lib/registryFixtures'

import { SkillDetail } from './skill-detail'

export default function SkillPage({ params }: { params: Promise<{ name: string }> }): React.ReactElement {
    const { name: rawName } = use(params)
    const name = decodeURIComponent(rawName)
    const teamId = useSessionTeamId()
    const [skill, setSkill] = useState<SkillTemplateDetail | null>(null)
    const [missing, setMissing] = useState(false)

    useEffect(() => {
        if (teamId == null) {
            return
        }
        let cancelled = false
        ;(async () => {
            try {
                const [detail, versions, usages] = await Promise.all([
                    getSkillTemplate(teamId, name),
                    listSkillTemplateVersions(teamId, name),
                    listSkillTemplateUsages(teamId, name),
                ])
                if (cancelled) {
                    return
                }
                // Merge the three responses into the shape `SkillDetail` consumes.
                // `versions` is newest-first and includes the current row — strip it
                // for the "older versions" list the UI renders.
                const history = versions
                    .filter((v) => v.version !== detail.version)
                    .map((v) => ({
                        version: v.version,
                        updated_at: v.updated_at,
                        created_by: v.created_by?.first_name ?? null,
                    }))
                setSkill({
                    ...detail,
                    description: detail.description ?? '',
                    created_by: detail.created_by?.first_name ?? null,
                    files: detail.files.map((f) => ({ path: f.path, content: f.content })),
                    history,
                    usages: usages.map((u) => ({
                        agent_slug: u.agent_slug,
                        agent_name: u.agent_name,
                        revision_short_id: u.revision_short_id,
                        pinned_version: u.pinned_version,
                    })),
                })
            } catch (e) {
                if (!cancelled && (e as { status?: number }).status === 404) {
                    setMissing(true)
                }
            }
        })()
        return () => {
            cancelled = true
        }
    }, [teamId, name])

    if (missing) {
        notFound()
    }
    if (!skill) {
        return <div className="px-6 py-6 text-sm text-muted-foreground">Loading skill template…</div>
    }
    return <SkillDetail skill={skill} />
}
