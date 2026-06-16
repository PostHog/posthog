/**
 * `/agents/[slug]/connections` — retired tab, kept as a redirect.
 *
 * Secrets, integrations, MCPs, and Slack setup all live in the
 * configuration explorer now. Old links (and concierge deep links that
 * predate the move) carry `?edit_secret=` / `?callback_session=` — preserve
 * them so the secret editor still opens on the configuration surface.
 */

'use client'

import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { useEffect } from 'react'

export default function ConnectionsRedirect(): null {
    const router = useRouter()
    const params = useParams()
    const searchParams = useSearchParams()

    useEffect(() => {
        const slug = typeof params?.slug === 'string' ? params.slug : Array.isArray(params?.slug) ? params.slug[0] : ''
        if (!slug) {
            return
        }
        const qs = searchParams?.toString()
        router.replace(`/agents/${slug}/configuration${qs ? `?${qs}` : ''}`)
    }, [params, router, searchParams])

    return null
}
