import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import { ApiConfig } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { mcpServersList } from 'products/mcp_store/frontend/generated/api'
import { MCPServerTemplateApi } from 'products/mcp_store/frontend/generated/api.schemas'
import { ServerIcon } from 'products/mcp_store/frontend/scene/icons'

const CONNECTOR_COUNT = 6

// Most-installed connectors first (store install counts, Oct 2026); the rest keep catalog order.
const POPULAR_CONNECTORS = ['Cloudflare', 'Linear', 'Supabase', 'Sentry', 'Stripe', 'Notion']

function byPopularity(a: MCPServerTemplateApi, b: MCPServerTemplateApi): number {
    const rank = (t: MCPServerTemplateApi): number => {
        const index = POPULAR_CONNECTORS.indexOf(t.name)
        return index === -1 ? POPULAR_CONNECTORS.length : index
    }
    return rank(a) - rank(b)
}

/**
 * Discovery section under the chat suggestions: popular MCP connectors and a link to skills.
 * Shown only with the today-rail-nav UX. The connector grid additionally needs the mcp-gateway
 * flag, since the page it links to sits behind it.
 */
export function MaxDiscovery(): JSX.Element | null {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const mcpGateway = useFeatureFlag('MCP_GATEWAY')

    if (!todayRailNav) {
        return null
    }

    return (
        <div className="flex flex-col items-center gap-2 w-full mt-4">
            {mcpGateway && <PopularConnectors />}
            <div className="flex items-center gap-1 text-xs text-secondary">
                <span>PostHog AI can also follow your team's playbooks.</span>
                <Link to={urls.skills()} className="text-xs" onClick={() => posthog.capture('max skills link clicked')}>
                    Browse skills
                </Link>
            </div>
        </div>
    )
}

function PopularConnectors(): JSX.Element | null {
    const [templates, setTemplates] = useState<MCPServerTemplateApi[] | null>(null)

    useEffect(() => {
        let mounted = true
        mcpServersList(String(ApiConfig.getCurrentTeamId()))
            .then((response) => {
                if (mounted) {
                    // One tile per vendor: the catalog can hold several templates under one name.
                    const seen = new Set<string>()
                    const unique = [...response.results].sort(byPopularity).filter((template) => {
                        if (seen.has(template.name)) {
                            return false
                        }
                        seen.add(template.name)
                        return true
                    })
                    setTemplates(unique.slice(0, CONNECTOR_COUNT))
                    posthog.capture('max popular connectors shown', {
                        connector_count: Math.min(response.results.length, CONNECTOR_COUNT),
                    })
                }
            })
            // The section is a suggestion, not core chat: a failed catalog load hides it.
            .catch(() => {
                if (mounted) {
                    setTemplates(null)
                }
            })
        return () => {
            mounted = false
        }
    }, [])

    if (!templates || templates.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col items-center gap-2 w-full">
            <h3 className="text-center text-xs font-medium mb-0 text-secondary">
                Popular connectors give PostHog AI more tools
            </h3>
            <div className="grid grid-cols-3 @md/max-welcome:grid-cols-6 gap-2 w-full max-w-120">
                {templates.map((template) => (
                    <Link
                        key={template.id}
                        to={urls.mcpGateway()}
                        className="flex flex-col items-center gap-1.5 rounded border border-primary bg-surface-primary p-2 text-default hover:border-accent"
                        onClick={() => posthog.capture('max popular connector clicked', { connector: template.name })}
                    >
                        <ServerIcon iconDomain={template.icon_domain} serverUrl={template.url} size={24} />
                        <span className="text-xs truncate max-w-full">{template.name}</span>
                    </Link>
                ))}
            </div>
            <Link
                to={urls.mcpGateway()}
                className="text-xs"
                onClick={() => posthog.capture('max view all connectors clicked')}
            >
                View all connectors
            </Link>
        </div>
    )
}
