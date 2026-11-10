import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { WATCHED_PRODUCT_ICONS } from './todayRowIcons'

const WATCHED =
    'Each day, PostHog checks your alerts, experiments, feature flags, workflows, support tickets and recordings.'

export function TodayForYouEmpty({ isNewProject }: { isNewProject: boolean }): JSX.Element {
    return (
        <Empty className="TodayEmpty" data-attr="today-for-you-empty">
            <EmptyHeader>
                <IconStack>
                    {WATCHED_PRODUCT_ICONS.map((icon, index) => (
                        <IconStackItem key={index} color={icon.color}>
                            {icon.glyph}
                        </IconStackItem>
                    ))}
                </IconStack>
                <EmptyTitle>{isNewProject ? 'Send your first events' : 'Nothing needs you today'}</EmptyTitle>
                <EmptyDescription>
                    {isNewProject
                        ? `${WATCHED} When your project sends events, what needs you shows up here.`
                        : `${WATCHED} When something changes that needs you, it shows up here.`}
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                {isNewProject ? (
                    <Button
                        size="sm"
                        variant="primary"
                        render={
                            <LinkPrimitive
                                to={urls.onboarding({
                                    productKey: ProductKey.PRODUCT_ANALYTICS,
                                    stepKey: OnboardingStepKey.INSTALL,
                                })}
                            />
                        }
                        data-attr="today-for-you-empty-install"
                    >
                        Install PostHog
                    </Button>
                ) : (
                    <Button
                        size="sm"
                        variant="outline"
                        render={<LinkPrimitive to={urls.alerts()} />}
                        data-attr="today-for-you-empty-alerts"
                    >
                        Set up alerts
                    </Button>
                )}
            </EmptyContent>
        </Empty>
    )
}
