import { IconExternal } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import { AI_TRAINING_URL } from './aiTrainingConstants'

function QuillAITrainingDescription({
    hasSignedBaa,
    isLocked,
}: {
    hasSignedBaa: boolean
    isLocked: boolean
}): JSX.Element {
    if (hasSignedBaa) {
        return (
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                You are opted out of internal AI training because you have a signed BAA with PostHog.
            </Text>
        )
    }

    if (isLocked) {
        return (
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Your organization's internal AI training preference is fixed by your contract and cannot be changed.
                Please contact us if you need to discuss this.
            </Text>
        )
    }

    return (
        <>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Enable PostHog to use anonymized aggregated data to train AI features that benefit all PostHog
                customers. <strong>Your and your customers' data stays with PostHog.</strong>
            </Text>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Opting out means that you cannot access certain AI features.
            </Text>
        </>
    )
}

export function QuillOrganizationAITrainingOptOut({
    hasSignedBaa,
    isLocked,
    checked,
    loading,
    disabledReason,
    onCheckedChange,
}: {
    hasSignedBaa: boolean
    isLocked: boolean
    checked: boolean
    loading: boolean
    disabledReason: string | undefined
    onCheckedChange: (checked: boolean) => void
}): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-2 max-w-160">
            <QuillAITrainingDescription hasSignedBaa={hasSignedBaa} isLocked={isLocked} />
            <QuillSettingSwitch
                label="Enable AI training on anonymized data"
                dataAttr="organization-ai-training-opt-in"
                checked={checked}
                onCheckedChange={onCheckedChange}
                disabled={loading}
                disabledReason={disabledReason}
            />
            <Button variant="primary" nativeButton={false} render={<LinkPrimitive to={AI_TRAINING_URL} />}>
                What's this?
                <IconExternal />
            </Button>
        </div>
    )
}
