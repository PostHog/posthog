import { useValues } from 'kea'

import { IconGlobe, IconLaptop, IconPhone, IconServer } from '@posthog/icons'
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton, Text } from '@posthog/quill'

import { goalSentence } from '../focusOptions'
import { guidedOnboardingLogic } from '../guidedOnboardingLogic'
import { GoalChart } from './GoalChart'
import { ProductTag } from './ProductTag'

const PLATFORM_ICONS = { web: <IconLaptop />, mobile: <IconPhone />, server: <IconServer /> }

/** Fills in as the user answers, so each question shows what it changes. */
export function PlanPreview(): JSX.Element {
    const { resolvedProjectName, resolvedWebsiteUrl, websiteUrlError, platforms, focus, resolvedTarget, products } =
        useValues(guidedOnboardingLogic)

    return (
        <Card>
            <CardHeader>
                <CardDescription>Your PostHog</CardDescription>
                <CardTitle className="flex min-w-0 items-center gap-2">
                    {platforms.map((platform) => (
                        <span key={platform} className="flex">
                            {PLATFORM_ICONS[platform]}
                        </span>
                    ))}
                    {resolvedProjectName.trim() ? (
                        <span className="truncate">{resolvedProjectName}</span>
                    ) : (
                        <Skeleton className="h-5 w-32" />
                    )}
                </CardTitle>
                {platforms.includes('web') && (
                    <Text size="xs" variant="muted" render={<div />} className="flex min-w-0 items-center gap-1">
                        <IconGlobe className="shrink-0" />
                        {resolvedWebsiteUrl.trim() && !websiteUrlError ? (
                            <span className="truncate" translate="no">
                                {resolvedWebsiteUrl.trim()}
                            </span>
                        ) : (
                            <Skeleton className="h-3 w-28" />
                        )}
                    </Text>
                )}
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                    <Text size="xs" variant="muted">
                        Goal
                    </Text>
                    {focus ? (
                        <>
                            <Text size="sm" weight="medium">
                                {goalSentence(focus, resolvedTarget)}
                            </Text>
                            {!focus.custom && (
                                <GoalChart direction={focus.goalVerb} target={resolvedTarget} metric={focus.metric} />
                            )}
                        </>
                    ) : (
                        <>
                            <Skeleton className="h-4 w-40" />
                            <Skeleton className="h-24 w-full" />
                        </>
                    )}
                </div>
                <div className="flex flex-col gap-2">
                    <Text size="xs" variant="muted">
                        Products for this goal
                    </Text>
                    <div className="flex flex-wrap gap-1">
                        {products.map((productKey) => (
                            <ProductTag key={productKey} productKey={productKey} />
                        ))}
                    </div>
                </div>
            </CardContent>
        </Card>
    )
}
