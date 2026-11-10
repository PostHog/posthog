import { useActions, useValues } from 'kea'

import { IconExpand45, IconExternal, IconMessage } from '@posthog/icons'
import {
    Badge,
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
    cn,
    toast,
} from '@posthog/quill'

import { IconLink } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { FEATURE_PREVIEW_SELF_HOSTED_DISABLED_REASON } from 'lib/logic/featureFlagLogic'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'
import { QuillFeaturePreviewFeedbackForm } from './QuillFeaturePreviewFeedbackForm'

const STAGE_LABELS: Record<string, string> = { alpha: 'Alpha', beta: 'Beta' }

export interface QuillFeaturePreviewCardProps {
    feature: EnrichedEarlyAccessFeature
    flagsHonored: boolean
    /** Optional warning rendered under the description (e.g. plan/add-on requirements). */
    warning?: React.ReactNode
}

export function QuillFeaturePreviewCard({ feature, flagsHonored, warning }: QuillFeaturePreviewCardProps): JSX.Element {
    const { activeFeedbackFlagKey } = useValues(featurePreviewsLogic)
    const {
        beginEarlyAccessFeatureFeedback,
        updateEarlyAccessFeatureEnrollment,
        copyExternalFeaturePreviewLink,
        openFeaturePreviewImage,
    } = useActions(featurePreviewsLogic)

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
        <Card id={flagKey} size="sm" className={cn(imageUrl && 'pt-0')}>
            {imageUrl && (
                <button
                    type="button"
                    className="group/image relative block cursor-zoom-in overflow-hidden rounded-t-lg border-b bg-muted"
                    onClick={() => openFeaturePreviewImage(flagKey)}
                    aria-label={`View a larger image of ${name}`}
                    data-attr="feature-preview-image"
                >
                    <img
                        src={imageUrl}
                        alt=""
                        loading="lazy"
                        className="block aspect-video w-full object-cover object-top"
                    />
                    <span className="absolute right-2 bottom-2 flex rounded-md bg-background p-1 text-foreground opacity-0 shadow-sm transition-opacity group-hover/image:opacity-100 group-focus-visible/image:opacity-100">
                        <IconExpand45 />
                    </span>
                </button>
            )}
            <CardHeader>
                <CardTitle className="flex min-w-0 flex-wrap items-center gap-2">
                    <label htmlFor={switchId} className={flagsHonored ? 'cursor-pointer' : 'cursor-default'}>
                        {name}
                    </label>
                    {STAGE_LABELS[stage] && (
                        <Badge variant={stage === 'alpha' ? 'warning' : 'info'}>{STAGE_LABELS[stage]}</Badge>
                    )}
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
            <CardFooter className="flex flex-wrap items-center gap-1">
                {!isFeedbackActive && (
                    <Button
                        onClick={() => beginEarlyAccessFeatureFeedback(flagKey)}
                        data-attr="feature-preview-give-feedback"
                    >
                        <IconMessage />
                        Give feedback
                    </Button>
                )}
                {documentationUrl && (
                    <Button render={<LinkPrimitive to={documentationUrl} target="_blank" />}>
                        Learn more
                        <IconExternal />
                    </Button>
                )}
                <Button
                    size="icon"
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
