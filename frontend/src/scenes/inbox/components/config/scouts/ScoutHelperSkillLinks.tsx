import { Link } from '@posthog/lemon-ui'

// General "learn more" entry point for scouts.
const SCOUTS_DOCS_URL = 'https://posthog.com/docs/self-driving/scouts'

// Desktop opens these two scout helper skills in its in-app Skills view; cloud has
// no in-app Skills surface, so they link out to the skill source on GitHub.
const HELPER_SKILLS = [
    {
        label: 'authoring scouts',
        url: 'https://github.com/PostHog/ai-plugin/blob/main/skills/authoring-scouts/SKILL.md',
    },
    {
        label: 'exploring scouts',
        url: 'https://github.com/PostHog/ai-plugin/blob/main/skills/exploring-scouts/SKILL.md',
    },
]

/** One-line footer: a "learn more" docs link plus pointers to the two official scout helper skills. */
export function ScoutHelperSkillLinks(): JSX.Element {
    return (
        <span className="text-xs text-muted">
            <Link to={SCOUTS_DOCS_URL} target="_blank">
                Learn more about scouts
            </Link>
            {' · Helper skills: '}
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
