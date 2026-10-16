import { Tooltip } from '@posthog/lemon-ui'

import { WIZARD_FRAMEWORKS, type WizardBadgeItem } from './WizardModeShell'

// A spread across web, backend and mobile reads as "works with my stack" better than the list's
// JS-heavy head.
const FEATURED_FRAMEWORKS = ['Next.js', 'React', 'Vue', 'Django', 'Laravel', 'Ruby on Rails', 'iOS', 'Android']

function FrameworkIcon({ item }: { item: WizardBadgeItem }): JSX.Element | null {
    if (!item.icon) {
        return null
    }
    return (
        <Tooltip title={item.name}>
            <span className="inline-flex w-4 h-4 shrink-0 [&_svg]:!w-4 [&_svg]:!h-4" aria-label={item.name}>
                {typeof item.icon === 'string' ? <img src={item.icon} alt="" className="w-4 h-4" /> : <item.icon />}
            </span>
        </Tooltip>
    )
}

export function WizardFrameworkIcons(): JSX.Element {
    const featured = WIZARD_FRAMEWORKS.filter((item) => FEATURED_FRAMEWORKS.includes(item.name))
    const rest = WIZARD_FRAMEWORKS.filter((item) => !FEATURED_FRAMEWORKS.includes(item.name))

    return (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <span>Works with</span>
            {featured.map((item) => (
                <FrameworkIcon key={item.name} item={item} />
            ))}
            {rest.length > 0 && (
                <Tooltip title={rest.map((item) => item.name).join(', ')}>
                    <span className="underline decoration-dotted cursor-default">+{rest.length} more</span>
                </Tooltip>
            )}
        </div>
    )
}
