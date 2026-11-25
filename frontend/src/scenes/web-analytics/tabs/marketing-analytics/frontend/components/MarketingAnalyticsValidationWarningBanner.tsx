import { IconExternal } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { LemonBanner } from '@posthog/lemon-ui'
import { Button, Item, ItemContent, ItemDescription } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'

enum ValidationWarningLink {
    MarketingAnalyticsSettings = 'marketing_analytics_settings',
}

interface MarketingAnalyticsValidationWarning {
    message: string
    /** Link to navigate to fix the issue */
    link?: ValidationWarningLink
}

export const validateConversionGoals = (goals: any[]): MarketingAnalyticsValidationWarning[] => {
    const warnings: MarketingAnalyticsValidationWarning[] = []

    for (const goal of goals) {
        if (goal.kind === NodeKind.EventsNode) {
            const event = 'event' in goal ? goal.event : null
            if (event === null || event === '') {
                warnings.push({
                    message: `Conversion goal "${goal.conversion_goal_name}" uses "All Events" which is not supported.`,
                    link: ValidationWarningLink.MarketingAnalyticsSettings,
                } as MarketingAnalyticsValidationWarning)
            }
        }
    }

    return warnings
}

interface MarketingAnalyticsValidationWarningBannerProps {
    warnings: MarketingAnalyticsValidationWarning[]
}

const getLinkUrl = (link: ValidationWarningLink): JSX.Element | null => {
    switch (link) {
        case ValidationWarningLink.MarketingAnalyticsSettings:
            return (
                <>
                    Check{' '}
                    <Link to={urls.settings('environment-marketing-analytics')} target="_blank">
                        marketing analytics settings
                        <IconExternal />
                    </Link>{' '}
                    for more details.
                </>
            )
        default:
            return null
    }
}

const getQuillLink = (link: ValidationWarningLink): JSX.Element | null => {
    switch (link) {
        case ValidationWarningLink.MarketingAnalyticsSettings:
            return (
                <>
                    Check{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.settings('environment-marketing-analytics')} target="_blank" />}
                    >
                        marketing analytics settings
                        <IconExternal />
                    </Button>{' '}
                    for more details.
                </>
            )
        default:
            return null
    }
}

export function MarketingAnalyticsValidationWarningBanner({
    warnings,
}: MarketingAnalyticsValidationWarningBannerProps): JSX.Element | null {
    const quillSurface = useQuillSurface()

    if (!warnings || warnings.length === 0) {
        return null
    }

    if (quillSurface) {
        return (
            <div className="flex flex-col gap-2">
                {warnings.map((warning, index) => (
                    <Item key={index} tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                {warning.message} {warning.link ? getQuillLink(warning.link) : null}
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                ))}
            </div>
        )
    }

    return (
        <>
            {warnings.map((warning, index) => (
                <LemonBanner key={index} type="warning" className="mb-2">
                    {warning.message} {warning.link ? getLinkUrl(warning.link) : null}
                </LemonBanner>
            ))}
        </>
    )
}
