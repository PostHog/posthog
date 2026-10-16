import posthog from 'posthog-js'

import { AccessDenied } from 'lib/components/AccessDenied'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { UnavailableSection } from '../types'

export function SettingSectionUnavailable({ section }: { section: UnavailableSection }): JSX.Element {
    useOnMountEffect(() => {
        // pinned: analytics event name, renaming it breaks dashboards
        posthog.capture('settings_section_unavailable_shown', { section_id: section.id, reason: section.reason })
    })

    const fallbackLink = section.fallback ? (
        <Link to={urls.settings(section.fallback.sectionId)} data-attr="settings-section-unavailable-fallback">
            {section.fallback.label}
        </Link>
    ) : null

    if (section.reason === 'admin-only') {
        return (
            <AccessDenied
                reason={
                    <>
                        {section.title} is available to organization admins and owners. {fallbackLink}
                    </>
                }
            />
        )
    }

    return (
        <div
            className="flex flex-col items-center gap-3 max-w-2xl p-4 mx-auto my-24 text-center"
            data-attr="settings-section-unavailable"
        >
            <h1 className="text-3xl font-bold mb-0">Not available yet</h1>
            <p className="text-sm mb-0">
                {section.title} is not enabled for your organization yet. Contact support if you need it now.
            </p>
            {fallbackLink}
        </div>
    )
}
