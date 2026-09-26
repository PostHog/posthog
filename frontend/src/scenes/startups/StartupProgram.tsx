import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import * as climber1Png from '@posthog/brand/hoggies/png/climber-1'
import * as hogpatchPng from '@posthog/brand/hoggies/png/hogpatch'
import { IconArrowRight, IconCheck, IconInfo, IconWarning } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Spinner,
    Text,
} from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { BillingProductV2Type, StartupProgramLabel } from '~/types'

import { DanglingHedgehog } from './DanglingHedgehog'
import { StartupProgramForm } from './StartupProgramForm'
import { StartupProgramLogicProps, startupProgramLogic } from './startupProgramLogic'

const HedgehogHogpatch = pngHoggie(hogpatchPng)
const HedgehogClimber = pngHoggie(climber1Png)

/** A page that says why the application is unavailable, and sends the reader back to the app. */
function StartupProgramNotice({ title, children }: { title: ReactNode; children: ReactNode }): JSX.Element {
    return (
        <div data-quill className="mx-auto w-full max-w-200 px-4 py-6">
            <Card>
                <CardHeader>
                    <CardTitle>{title}</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col items-start gap-2">
                    {children}
                    <Button variant="primary" render={<LinkPrimitive to={urls.projectRoot()} />}>
                        Return to PostHog
                    </Button>
                </CardContent>
            </Card>
        </div>
    )
}

/**
 * Does not use `BillingUpgradeCTA`, which is a Lemon button. It reports the same
 * `reportBillingCTAShown` event, so the CTA still counts as shown wherever that event is read.
 */
function BillingUpgradeButton({
    platformAndSupportProduct,
}: {
    platformAndSupportProduct: BillingProductV2Type
}): JSX.Element {
    const { billing } = useValues(billingLogic)
    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)
    const { billingProductLoading } = useValues(billingProductLogic({ product: platformAndSupportProduct }))
    const { reportBillingCTAShown } = useActions(eventUsageLogic)
    useOnMountEffect(reportBillingCTAShown)

    return (
        <Button
            variant="primary"
            size="lg"
            data-attr="startup-program-upgrade-cta"
            loading={!!billingProductLoading}
            onClick={() =>
                startPaymentEntryFlow(platformAndSupportProduct, window.location.pathname + window.location.search)
            }
        >
            {billing?.customer_id ? 'Subscribe' : 'Add billing details'}
        </Button>
    )
}

export const scene: SceneExport<StartupProgramLogicProps> = {
    component: StartupProgram,
    logic: startupProgramLogic,
    paramsToProps: ({ params: { referrer } }) => ({ referrer: referrer || undefined }),
}

export function StartupProgram(): JSX.Element {
    const {
        isCurrentlyOnStartupPlan,
        wasPreviouslyOnStartupPlan,
        isAdminOrOwner,
        isAnnualPlanCustomer,
        isYC,
        isReferralProgram,
        referrerDisplayName,
        currentStartupProgramLabel,
        formSubmitted,
        shouldShowEmailDomainBlockedGate,
        user,
    } = useValues(startupProgramLogic)
    const { billing, billingLoading, accountOwner } = useValues(billingLogic)

    const currentProgramName = currentStartupProgramLabel === StartupProgramLabel.YC ? 'YC Program' : 'Startup Program'
    const platformAndSupportProduct = billing?.products?.find(
        (product) => product.type === ProductKey.PLATFORM_AND_SUPPORT
    )

    // Show early return banner only for non-YC pages when already on a plan
    // For YC pages, we show the full page with a status box instead
    if (isCurrentlyOnStartupPlan && !isYC) {
        return (
            <StartupProgramNotice title={`You are already in the ${currentProgramName}`}>
                <Text>It looks like your organization is already part of our {currentProgramName}.</Text>
                {currentStartupProgramLabel === StartupProgramLabel.YC && (
                    <Text>
                        Your credits will renew automatically <span className="font-semibold">every year, forever</span>
                        , until you hit $25M in funding.
                    </Text>
                )}
                <Text>If you have any questions, please contact our support team.</Text>
            </StartupProgramNotice>
        )
    }

    // YC customers can re-apply
    if (wasPreviouslyOnStartupPlan && !isYC) {
        return (
            <StartupProgramNotice title="You were already in the Startup Program">
                <Text>
                    It looks like your organization was already part of our Startup Program. If you have any questions,
                    please contact our support team.
                </Text>
            </StartupProgramNotice>
        )
    }

    if (isAnnualPlanCustomer) {
        return (
            <StartupProgramNotice title="You are already on an annual plan">
                <Text>
                    It looks like your organization is already on our annual plan. If you have any questions, please
                    contact{' '}
                    {accountOwner?.name && accountOwner?.email
                        ? `your PostHog human ${accountOwner.name.split(' ')[0]} at ${accountOwner.email}`
                        : 'our support team'}
                </Text>
            </StartupProgramNotice>
        )
    }

    if (!isAdminOrOwner) {
        return (
            <StartupProgramNotice
                title={
                    <span className="flex items-center gap-2">
                        <IconWarning className="text-warning" />
                        Admin or owner permission required
                    </span>
                }
            >
                <Text>
                    You need to be an organization admin or owner to apply for the startup program. Please contact your
                    organization admin for assistance.
                </Text>
            </StartupProgramNotice>
        )
    }

    return (
        <div data-quill className="@container/startup-page flex min-h-full">
            <div className="@container/startup-content flex-1 min-w-0 px-3 py-6 pb-16 @min-[32rem]/startup-content:px-4">
                <div className="mx-auto flex max-w-[1000px] flex-col gap-8">
                    <div className="flex flex-col items-center gap-2 @min-[32rem]/startup-content:flex-row @min-[32rem]/startup-content:items-end @min-[32rem]/startup-content:gap-4">
                        <div className="w-24 shrink-0 @min-[32rem]/startup-content:w-35">
                            {isYC ? (
                                <HedgehogHogpatch className="h-auto w-full" />
                            ) : (
                                <HedgehogClimber className="h-auto w-full" />
                            )}
                        </div>
                        <div className="flex flex-col gap-2 text-center">
                            <Heading size="2xl" render={<h1 />}>
                                {isYC
                                    ? "You've found our secret Y Combinator offer!"
                                    : isReferralProgram && referrerDisplayName
                                      ? `PostHog x ${referrerDisplayName}`
                                      : "Apply for PostHog's startup program"}
                            </Heading>
                            {isYC ? (
                                <Text variant="muted">
                                    Get $50,000 in credits <span className="font-semibold">every. year. forever.</span>{' '}
                                    (plus extras you'll actually use) to help you get to product-market fit. You'll keep
                                    getting them until you hit $25M in funding.
                                </Text>
                            ) : (
                                <Text variant="muted">
                                    Get $50,000 in credits (plus extras you'll actually use) to help you get to
                                    product-market fit.
                                </Text>
                            )}
                        </div>
                    </div>

                    <div className="grid items-start gap-4 @min-[56rem]/startup-content:grid-cols-2">
                        <Card flush>
                            <CardHeader>
                                <CardTitle>
                                    {isReferralProgram && referrerDisplayName
                                        ? `We've teamed up with ${referrerDisplayName} to offer you`
                                        : 'What you can get'}
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="flex flex-col gap-4">
                                <ItemGroup className="gap-0">
                                    <Item>
                                        <ItemMedia variant="icon">
                                            <IconCheck className="text-success" />
                                        </ItemMedia>
                                        <ItemContent>
                                            <ItemTitle>
                                                $50,000 in PostHog credit
                                                {isYC && (
                                                    <>
                                                        {' '}
                                                        every. year. forever.
                                                        <span className="text-[0.66em] align-super text-muted"> 1</span>
                                                    </>
                                                )}
                                            </ItemTitle>
                                            <ItemDescription>
                                                {isYC
                                                    ? 'Valid to use across all products'
                                                    : 'Valid for 1 year to use across all products'}
                                            </ItemDescription>
                                        </ItemContent>
                                    </Item>
                                    <Item>
                                        <ItemMedia variant="icon">
                                            <IconCheck className="text-success" />
                                        </ItemMedia>
                                        <ItemContent>
                                            <ItemTitle>
                                                Exclusive founder merch
                                                {isYC && (
                                                    <span className="text-[0.66em] align-super text-muted"> 2</span>
                                                )}
                                            </ItemTitle>
                                            <ItemDescription>
                                                Who wouldn't want free laptop stickers, hats, or t-shirts?
                                            </ItemDescription>
                                        </ItemContent>
                                    </Item>
                                    <Item>
                                        <ItemMedia variant="icon">
                                            <IconCheck className="text-success" />
                                        </ItemMedia>
                                        <ItemContent>
                                            <ItemTitle>$1,500 off an Incident.io teams plan</ItemTitle>
                                            <ItemDescription>
                                                So you can avoid stress during an incident
                                            </ItemDescription>
                                        </ItemContent>
                                    </Item>
                                    <Item>
                                        <ItemMedia variant="icon">
                                            <IconCheck className="text-success" />
                                        </ItemMedia>
                                        <ItemContent>
                                            <ItemTitle>50% off Speakeasy for 6 months</ItemTitle>
                                            <ItemDescription>So you can build better APIs, faster</ItemDescription>
                                        </ItemContent>
                                    </Item>
                                    <Item>
                                        <ItemMedia variant="icon">
                                            <IconCheck className="text-success" />
                                        </ItemMedia>
                                        <ItemContent>
                                            <ItemTitle>$5,000 in Chroma credit</ItemTitle>
                                            <ItemDescription>Great for building better AI agents</ItemDescription>
                                        </ItemContent>
                                    </Item>
                                    {isYC && (
                                        <Item>
                                            <ItemMedia variant="icon">
                                                <IconCheck className="text-success" />
                                            </ItemMedia>
                                            <ItemContent>
                                                <ItemTitle>Priority support</ItemTitle>
                                                <ItemDescription>
                                                    Direct access to our engineering team for technical support
                                                </ItemDescription>
                                            </ItemContent>
                                        </Item>
                                    )}
                                </ItemGroup>

                                {!isYC && (
                                    <div className="flex flex-col gap-1 pb-2">
                                        {/* Padded to the same left edge as the rows below, which get
                                            their inline padding from Item. */}
                                        <Heading size="sm" className="px-3" render={<h3 />}>
                                            As long as
                                        </Heading>
                                        <ItemGroup className="gap-0">
                                            <Item>
                                                <ItemMedia variant="icon">
                                                    <IconArrowRight />
                                                </ItemMedia>
                                                <ItemContent>
                                                    <ItemTitle>
                                                        Your company was founded less than 2 years ago
                                                    </ItemTitle>
                                                </ItemContent>
                                            </Item>
                                            <Item>
                                                <ItemMedia variant="icon">
                                                    <IconArrowRight />
                                                </ItemMedia>
                                                <ItemContent>
                                                    <ItemTitle>You've raised less than $5 million in funding</ItemTitle>
                                                </ItemContent>
                                            </Item>
                                        </ItemGroup>
                                    </div>
                                )}

                                {isYC && (
                                    <div className="flex flex-col gap-1 px-3 pb-3">
                                        <Text size="xs" variant="muted" className="flex gap-1">
                                            <span className="text-xxs align-super">1</span>
                                            Credits renew automatically each year until you hit $25M in funding. If
                                            you've previously been in the program and your credits expired, you can
                                            reapply and continue getting $50,000 annually.
                                        </Text>
                                        <Text size="xs" variant="muted" className="flex gap-1">
                                            <span className="text-xxs align-super">2</span>
                                            Boring international customs reasons mean users outside US/Canada get a $150
                                            PostHog merch voucher instead.
                                        </Text>
                                    </div>
                                )}
                            </CardContent>
                        </Card>

                        <div className="flex flex-col gap-4">
                            {/* Show status box for current startup plan customers visiting YC page */}
                            {isCurrentlyOnStartupPlan && isYC ? (
                                <Card>
                                    <CardHeader>
                                        <CardTitle className="flex items-center gap-2">
                                            <IconCheck className="text-success" />
                                            You're in the {currentProgramName}
                                        </CardTitle>
                                    </CardHeader>
                                    <CardContent className="flex flex-col items-start gap-2">
                                        {currentStartupProgramLabel === StartupProgramLabel.YC ? (
                                            <Text>
                                                Your credits will renew automatically{' '}
                                                <span className="font-semibold">every year, forever</span>, until you
                                                hit $25M in funding.
                                            </Text>
                                        ) : (
                                            <Text>
                                                If you qualify for the YC Program and your Startup Program credits
                                                expire, you can reapply for the YC deal and receive $50,000 in credits
                                                annually.
                                            </Text>
                                        )}
                                        <Text>If you have any questions, please contact our support team.</Text>
                                        <Button variant="primary" render={<LinkPrimitive to={urls.projectRoot()} />}>
                                            Return to PostHog
                                        </Button>
                                    </CardContent>
                                </Card>
                            ) : (
                                <>
                                    <Card>
                                        <CardHeader>
                                            <CardTitle>Step 1: Add billing details</CardTitle>
                                        </CardHeader>
                                        <CardContent>
                                            {billingLoading ? (
                                                <Text className="flex items-center gap-2">
                                                    <Spinner />
                                                    Checking if you're on a paid plan
                                                </Text>
                                            ) : billing?.has_active_subscription ? (
                                                <Text className="text-success flex items-center gap-2">
                                                    <IconCheck className="shrink-0" />
                                                    You're on a paid plan
                                                </Text>
                                            ) : (
                                                <div className="flex flex-col items-start gap-2">
                                                    <Text variant="muted">
                                                        To be eligible for the startup program, you need to be on a paid
                                                        plan.
                                                    </Text>
                                                    <Text variant="muted">
                                                        Don't worry - you'll only pay for what you use and can set
                                                        billing limits as low as $0 to control your spend.
                                                    </Text>
                                                    <Text variant="muted" className="italic">
                                                        P.S. You still keep the monthly free allowance for every
                                                        product!
                                                    </Text>
                                                    {platformAndSupportProduct && (
                                                        <BillingUpgradeButton
                                                            platformAndSupportProduct={platformAndSupportProduct}
                                                        />
                                                    )}
                                                </div>
                                            )}
                                        </CardContent>
                                    </Card>

                                    <Card>
                                        <CardHeader>
                                            <CardTitle>Step 2: Submit application</CardTitle>
                                        </CardHeader>
                                        <CardContent className="flex flex-col gap-4">
                                            {/* Show reapplication banner for YC users who were previously in a program */}
                                            {wasPreviouslyOnStartupPlan && isYC && (
                                                <Text size="sm" variant="muted" className="flex items-start gap-2">
                                                    <IconInfo className="shrink-0" />
                                                    You can reapply for the YC Program and receive $50,000 in credits
                                                    annually, renewed each year.
                                                </Text>
                                            )}

                                            {formSubmitted ? (
                                                <Empty>
                                                    <EmptyHeader>
                                                        <EmptyMedia variant="icon">
                                                            <IconCheck className="text-success" />
                                                        </EmptyMedia>
                                                        <EmptyTitle>Application submitted successfully!</EmptyTitle>
                                                        <EmptyDescription>
                                                            Thank you for your application! We'll review it and get back
                                                            to you as soon as possible. In the meantime, you can
                                                            continue using PostHog.
                                                        </EmptyDescription>
                                                    </EmptyHeader>
                                                    <EmptyContent>
                                                        <Button
                                                            variant="primary"
                                                            render={<LinkPrimitive to={urls.projectRoot()} />}
                                                        >
                                                            Return to PostHog
                                                        </Button>
                                                    </EmptyContent>
                                                </Empty>
                                            ) : shouldShowEmailDomainBlockedGate ? (
                                                <Empty>
                                                    <EmptyHeader>
                                                        <EmptyMedia variant="icon">
                                                            <IconWarning className="text-warning" />
                                                        </EmptyMedia>
                                                        <EmptyTitle>A company email is required</EmptyTitle>
                                                        <EmptyDescription>
                                                            You're signed in as {user?.email}, which uses a personal
                                                            email domain. The startup program requires a company email
                                                            address. Change your account email in settings and verify
                                                            it, then come back to apply.
                                                        </EmptyDescription>
                                                    </EmptyHeader>
                                                    <EmptyContent>
                                                        <Button
                                                            variant="primary"
                                                            render={<LinkPrimitive to={urls.settings('user')} />}
                                                        >
                                                            Update your email
                                                        </Button>
                                                    </EmptyContent>
                                                </Empty>
                                            ) : (
                                                <StartupProgramForm />
                                            )}
                                        </CardContent>
                                    </Card>
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </div>
            <DanglingHedgehog className="hidden @min-[80rem]/startup-page:block" />
        </div>
    )
}

export default StartupProgram
