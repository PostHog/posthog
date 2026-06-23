import { Link } from '@posthog/lemon-ui'

// Desktop opens these two scout helper skills in its in-app Skills view; cloud has
// no in-app Skills surface, so they link out to the equivalent PostHog docs.
const HELPER_SKILLS = [
    { label: 'authoring scouts', url: 'https://posthog.com/docs/signals' },
    { label: 'exploring scouts', url: 'https://posthog.com/docs/signals' },
]

/** One-line pointer to the two official scout helper skills. */
export function ScoutHelperSkillLinks(): JSX.Element {
    return (
        <span className="text-xs text-muted">
            Helper skills:{' '}
            {HELPER_SKILLS.map((skill, index) => (
                <span key={skill.label}>
                    {index > 0 ? ' · ' : null}
                    <Link to={skill.url} target="_blank">
                        {skill.label}
                    </Link>
                </span>
            ))}
        </span>
    )
}
