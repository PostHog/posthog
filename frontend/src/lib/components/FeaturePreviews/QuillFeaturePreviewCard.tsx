import { useActions, useValues } from 'kea'

import { IconExternal, IconMessage } from '@posthog/icons'
import {
    Button,
    Card,
    CardAction,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle,
    Item,
    ItemContent,
    ItemDescription,
    Switch,
    Text,
    toast,
} from '@posthog/quill'

import { IconLink } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { FEATURE_PREVIEW_SELF_HOSTED_DISABLED_REASON } from 'lib/logic/featureFlagLogic'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'
import { QuillFeaturePreviewFeedbackForm } from './QuillFeaturePreviewFeedbackForm'
import { QuillFeaturePreviewImage } from './QuillFeaturePreviewImage'

export interface QuillFeaturePreviewCardProps {
    feature: EnrichedEarlyAccessFeature
    flagsHonored: boolean
    /** Optional warning rendered under the description (e.g. plan/add-on requirements). */
    warning?: React.ReactNode
}

export function QuillFeaturePreviewCard({ feature, flagsHonored, warning }: QuillFeaturePreviewCardProps): JSX.Element {
    const { activeFeedbackFlagKey } = useValues(featurePreviewsLogic)
    const { beginEarlyAccessFeatureFeedback, updateEarlyAccessFeatureEnrollment, copyExternalFeaturePreviewLink } =
        useActions(featurePreviewsLogic)

    const { flagKey, enabled, name, description, documentationUrl, imageUrl, stage } = feature
    const isFeedbackActive = activeFeedbackFlagKey === flagKey
    const switchId = `${flagKey}-switch`

    const onCheckedChange = (checked: boolean): void => {
        updateEarlyAccessFeatureEnrollment(flagKey, checked, stage)
        if (checked && !window.IMPERSONATED_SESSION) {
            toast.success({
                title: `${name} is on`,
                description: 'Let us know how it works for you.',
                action: { label: 'Give feedback', onClick: () => beginEarlyAccessFeatureFeedback(flagKey) },
            })
        }
    }

    return (
        <Card id={flagKey} size="sm">
            {imageUrl && <QuillFeaturePreviewImage feature={feature} className="mx-3 aspect-[3/1]" />}
            <CardHeader>
                <CardTitle className="min-w-0">
                    <label htmlFor={switchId} className={flagsHonored ? 'cursor-pointer' : 'cursor-default'}>
                        {name}
                    </label>
                </CardTitle>
                <CardAction>
                    <Switch
                        id={switchId}
                        checked={enabled}
                        onCheckedChange={onCheckedChange}
                        disabledReason={!flagsHonored ? FEATURE_PREVIEW_SELF_HOSTED_DISABLED_REASON : undefined}
                        data-attr="feature-preview-switch"
                    />
                </CardAction>
            </CardHeader>
            <CardContent className="flex flex-1 flex-col gap-2">
                <Text size="xs" variant={description ? 'default' : 'muted'} render={<p />} className="m-0">
                    {description || 'No description'}
                </Text>
                {warning && (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>{warning}</ItemDescription>
                        </ItemContent>
                    </Item>
                )}
                {isFeedbackActive && <QuillFeaturePreviewFeedbackForm feature={feature} />}
            </CardContent>
            <CardFooter className="flex flex-wrap items-center gap-1 py-1.5">
                {!isFeedbackActive && (
                    <Button
                        size="sm"
                        onClick={() => beginEarlyAccessFeatureFeedback(flagKey)}
                        data-attr="feature-preview-give-feedback"
                    >
                        <IconMessage />
                        Give feedback
                    </Button>
                )}
                {documentationUrl && (
                    <Button size="sm" render={<LinkPrimitive to={documentationUrl} target="_blank" />}>
                        Learn more
                        <IconExternal />
                    </Button>
                )}
                <Button
                    size="icon-sm"
                    className="ms-auto"
                    aria-label="Copy link to this preview"
                    tooltip="Copy link to this preview"
                    onClick={() => copyExternalFeaturePreviewLink(flagKey)}
                >
                    <IconLink />
                </Button>
            </CardFooter>
        </Card>
    )
}
