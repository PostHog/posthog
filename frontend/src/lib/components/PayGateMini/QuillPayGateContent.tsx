import { useValues } from 'kea'

import { IconInfo, IconOpenSidebar, IconUnlock } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AvailableFeature } from '~/types'

import { PayGateButton } from './PayGateButton'
import { PayGateMiniLogicProps, payGateMiniLogic } from './payGateMiniLogic'

export function QuillPayGateContent({
    feature,
    currentUsage,
    className,
    background,
    isGrandfathered,
    handleCtaClick,
    learnMoreUrl,
    onBypass,
    renderProductIcon,
}: PayGateMiniLogicProps & {
    renderProductIcon: (iconKey: string | null | undefined) => JSX.Element
    className?: string
    background: boolean
    isGrandfathered?: boolean
    handleCtaClick: () => void
    /** Set when the docs link button should show. */
    learnMoreUrl: string | null
    /** Set when staff impersonating the user may bypass the paywall. */
    onBypass: (() => void) | null
}): JSX.Element | null {
    const {
        productWithFeature,
        featureInfo,
        featureAvailableOnOrg,
        gateVariant,
        isAddonProduct,
        featureInfoOnNextPlan,
    } = useValues(payGateMiniLogic({ feature, currentUsage }))

    if (!productWithFeature || !featureInfo) {
        return null
    }

    const content = (
        <div className="flex flex-col items-center gap-2 text-center">
            <div className="flex text-4xl text-warning-foreground">{renderProductIcon(featureInfo.icon_key)}</div>
            <Heading size="sm" render={<h3 className="m-0" />}>
                {featureInfo.name}
            </Heading>

            {featureAvailableOnOrg?.limit && gateVariant !== 'move-to-cloud' ? (
                <>
                    <Text size="xs" render={<p className="m-0" />}>
                        You've reached your usage limit for{' '}
                        <Tooltip>
                            <TooltipTrigger
                                render={<span className="inline-flex items-center gap-0.5 font-semibold" />}
                            >
                                {featureInfo.name}
                                <IconInfo className="text-muted-foreground" />
                            </TooltipTrigger>
                            <TooltipContent>{featureInfo.description}</TooltipContent>
                        </Tooltip>
                        .
                    </Text>
                    <Text size="xs" render={<p className="m-0 rounded-md border border-border px-3 py-2" />}>
                        <strong>Your current plan limit:</strong>{' '}
                        <span>
                            {featureAvailableOnOrg.limit} {featureAvailableOnOrg.unit}
                        </span>
                    </Text>
                    {featureInfo.key === AvailableFeature.ORGANIZATIONS_PROJECTS && !isAddonProduct ? (
                        <>
                            {featureInfoOnNextPlan?.limit && (
                                <Text size="xs" render={<p className="m-0" />}>
                                    Please enter your credit card details to create up to{' '}
                                    <strong>{featureInfoOnNextPlan?.limit} projects</strong>.
                                </Text>
                            )}
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                Need unlimited projects? Check out one of our{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to="/organization/billing?products=platform_and_support" />}
                                    onClick={handleCtaClick}
                                >
                                    platform add-ons
                                </Button>
                                .
                            </Text>
                        </>
                    ) : !isAddonProduct ? (
                        <Text size="xs" render={<p className="m-0" />}>
                            Upgrade to create more {featureInfo.name}
                        </Text>
                    ) : (
                        <Text size="xs" render={<p className="m-0" />}>
                            Upgrade your <strong>{productWithFeature.name}</strong> plan to create more{' '}
                            {featureInfo.name}
                        </Text>
                    )}
                </>
            ) : (
                <>
                    <Text size="xs" render={<p className="m-0 max-w-140" />}>
                        {featureInfo.description}
                    </Text>
                    <Text size="xs" render={<p className="m-0" />}>
                        {gateVariant === 'move-to-cloud' ? (
                            <>This feature is only available on PostHog Cloud.</>
                        ) : isAddonProduct ? (
                            <>
                                Subscribe to the <strong>{productWithFeature?.name}</strong> addon to use this feature.
                            </>
                        ) : (
                            <>Upgrade to use this feature.</>
                        )}
                    </Text>
                </>
            )}

            {isGrandfathered && (
                <Item tone="info" size="sm" className="text-left">
                    <ItemContent>
                        <ItemDescription>
                            Your plan does not include this feature, but previously set settings may remain. Please
                            upgrade your plan to regain access.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}

            {featureInfo.docsUrl && (
                <Text size="xs" render={<p className="m-0" />}>
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={featureInfo.docsUrl} target="_blank" />}
                    >
                        Learn more in PostHog Docs.
                    </Button>
                </Text>
            )}

            <div className="flex flex-wrap items-center justify-center gap-2">
                <PayGateButton feature={feature} currentUsage={currentUsage} onClick={handleCtaClick} />
                {learnMoreUrl && (
                    <Button
                        variant="outline"
                        nativeButton={false}
                        render={<LinkPrimitive to={learnMoreUrl} target="_blank" />}
                        data-attr={`${feature}-learn-more`}
                    >
                        Learn more
                        <IconOpenSidebar />
                    </Button>
                )}
                {onBypass && (
                    <Button variant="outline" tooltip="Bypass this paywall - (UI only)" onClick={onBypass}>
                        <IconUnlock />
                        Bypass paywall
                    </Button>
                )}
            </div>
        </div>
    )

    return background ? (
        <Card className={className}>
            <CardContent>{content}</CardContent>
        </Card>
    ) : (
        <div data-quill className={className}>
            {content}
        </div>
    )
}
