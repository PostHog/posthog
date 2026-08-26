import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect, LemonSelectOption } from 'lib/lemon-ui/LemonSelect'

const ROLE_OPTIONS: LemonSelectOption<string>[] = [
    { label: 'Engineering', value: 'engineering' },
    { label: 'Data', value: 'data' },
    { label: 'Product Management', value: 'product' },
    { label: 'Founder', value: 'founder' },
    { label: 'Leadership', value: 'leadership' },
    { label: 'Marketing', value: 'marketing' },
    { label: 'Sales / Success', value: 'sales' },
    { label: 'Student', value: 'student' },
]

const OTHER_ROLE_OPTION: LemonSelectOption<string> = { label: 'Other', value: 'other' }

// Fisher-Yates, so every ordering is equally likely rather than merely jumbled
const shuffle = <T,>(items: T[]): T[] => {
    const shuffled = [...items]
    for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1))
        ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
    }
    return shuffled
}

// Roles are shuffled so their order doesn't sway what people pick, with "Other" pinned last.
// Done at module scope so the list is stable for the page rather than reordering on every render.
const roleOptions = [...shuffle(ROLE_OPTIONS), OTHER_ROLE_OPTION]

export default function SignupRoleSelect({ className }: { className?: string }): JSX.Element {
    return (
        <LemonField name="role_at_organization" label="What is your role?" className={className}>
            <LemonSelect fullWidth data-attr="signup-role-at-organization" options={roleOptions} />
        </LemonField>
    )
}
