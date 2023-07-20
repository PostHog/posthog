import { Field } from 'lib/forms/Field'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

export default function SignupReferralSourceSelect({ className }: { className?: string }): JSX.Element {
    return (
        <Field name="referral_source" label="Where did you hear about us?" className={className} showOptional>
            <LemonSelect
                fullWidth
                data-attr="signup-referral-source"
                options={[
                    {
                        label: 'Friend or co-worker recommended',
                        value: 'friend-recommendation',
                    },
                    {
                        label: "I've used it before",
                        value: 'prior-use',
                    },
                    {
                        label: 'Read a blog post or newsletter',
                        value: 'blog-post',
                    },
                    {
                        label: 'Online forum (Reddit, Hacker News, Slack etc.)',
                        value: 'online-forum',
                    },
                    {
                        label: 'Twitter',
                        value: 'twitter',
                    },
                    {
                        label: 'GitHub',
                        value: 'github',
                    },
                    {
                        label: 'Other',
                        value: 'other',
                    },
                ]}
            />
        </Field>
    )
}
