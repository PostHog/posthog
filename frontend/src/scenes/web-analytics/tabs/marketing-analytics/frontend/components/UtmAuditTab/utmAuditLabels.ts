import type { CampaignAuditResult, UtmIssueKind } from '../../logic/utmAuditLogic'

const DISPLAY_NAMES: Record<string, string> = {
    google: 'Google Ads',
    meta: 'Meta Ads',
    linkedin: 'LinkedIn Ads',
    tiktok: 'TikTok Ads',
    reddit: 'Reddit Ads',
    bing: 'Bing Ads',
    snapchat: 'Snapchat Ads',
    pinterest: 'Pinterest Ads',
    GoogleAds: 'Google Ads',
    MetaAds: 'Meta Ads',
    LinkedinAds: 'LinkedIn Ads',
    TikTokAds: 'TikTok Ads',
    RedditAds: 'Reddit Ads',
    BingAds: 'Bing Ads',
    SnapchatAds: 'Snapchat Ads',
    PinterestAds: 'Pinterest Ads',
}

export function sourceLabel(source: string): string {
    return DISPLAY_NAMES[source] || source
}

// Keyed by the generated issue-kind union, so a new kind added on the backend fails the typecheck
// here instead of silently falling back to the wrong label.
const ISSUE_LABELS: Record<UtmIssueKind, string> = {
    not_linked: 'Not linked',
    missing_source: 'Missing source',
    name_collision: 'Name collision',
    no_tagged_events: 'Source mismatch',
    unknown_source: 'Source mismatch',
}

function joinSources(sources: string[]): string {
    if (sources.length < 2) {
        return sources[0] ?? ''
    }
    return `${sources.slice(0, -1).join(', ')} or ${sources[sources.length - 1]}`
}

// Compose scoped, honest text for a campaign's status pill. The pill label is intentionally
// terse; this explains what the audit actually found for this specific campaign.
export function issueTooltip(record: CampaignAuditResult): string {
    const issue = record.issues[0]
    if (!issue) {
        return ''
    }
    const platform = sourceLabel(record.source_name)
    const fix = `Add utm_source=${record.source_name} to your ${platform} tracking URLs.`
    // A campaign is classified by its mistagged pageviews, so untagged ones ride along as an extra
    // sentence rather than disappearing. Zero on kinds where it can't happen.
    const untagged = issue.missing_source_count ?? 0
    const untaggedNote =
        untagged > 0 ? ` A further ${formatNumber(untagged)} pageviews arrived with no utm_source at all.` : ''

    switch (issue.kind) {
        case 'not_linked':
            return `No pageviews were found for this campaign. Check that your ${platform} tracking URLs include utm_source and utm_campaign.`
        case 'missing_source':
            return `${formatNumber(untagged)} pageviews reached this campaign with no utm_source set, so they can't be attributed to ${platform}. ${fix}`
        case 'name_collision': {
            const shared = (issue.shared_with_integrations ?? []).map(sourceLabel).join(', ') || 'another integration'
            return `This campaign's name is also used by ${shared}. Switch to matching on campaign ID so they can be told apart.${untaggedNote}`
        }
        case 'no_tagged_events':
        case 'unknown_source': {
            const sources = joinSources((issue.alternative_sources ?? []).map((s) => s.utm_source).filter(Boolean))
            if (!sources) {
                return issue.message
            }
            return `Pageviews matched this campaign, but their utm_source was ${sources}, not ${record.source_name}. ${fix}${untaggedNote}`
        }
        default:
            return issue.message
    }
}

// Short pill label reflecting the issue kind. The tooltip carries the full explanation.
export function issueLabel(record: CampaignAuditResult): string {
    const kind = record.issues[0]?.kind
    return (kind && ISSUE_LABELS[kind]) || 'Source mismatch'
}

export function formatNumber(value: number): string {
    return new Intl.NumberFormat('en-US').format(value)
}
