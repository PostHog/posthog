import { IconBug, IconLive, IconMap, IconQuestion, IconSparkles } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link/Link'
import { IconFeedback, IconQuestionAnswer } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from 'lib/ui/PopoverPrimitive/PopoverPrimitive'
import { urls } from 'scenes/urls'

export function HelpMenu(): JSX.Element {
    return (
        <PopoverPrimitive>
            <PopoverPrimitiveTrigger asChild>
                <ButtonPrimitive tooltip="Help" iconOnly>
                    <span className="flex group-hover:text-primary">
                        <IconQuestion className="size-5" />
                    </span>
                </ButtonPrimitive>
            </PopoverPrimitiveTrigger>
            <PopoverPrimitiveContent side="bottom" align="start" className="w-[500px] p-2">
                <Link to={urls.ai()} buttonProps={{ menuItem: true }}>
                    <IconSparkles />
                    Contact support
                </Link>
                <Link to={urls.ai()} buttonProps={{ menuItem: true }}>
                    <IconFeedback />
                    Give feedback
                </Link>
                <Link to={urls.ai()} buttonProps={{ menuItem: true }}>
                    <IconBug />
                    Report a bug
                </Link>
                <Link to={urls.ai()} buttonProps={{ menuItem: true }}>
                    <IconSparkles />
                    Ask PostHog AI for help
                </Link>
                <Link targetBlankIcon to="https://posthog.com/questions" buttonProps={{ menuItem: true }}>
                    <IconQuestionAnswer />
                    Ask the community
                </Link>
                <Link targetBlankIcon to="https://posthog.com/roadmap" buttonProps={{ menuItem: true }}>
                    <IconMap />
                    Roadmap
                </Link>
                <Link
                    targetBlankIcon
                    to="https://github.com/PostHog/posthog/issues/new?&labels=enhancement&template=feature_request.yml"
                    buttonProps={{ menuItem: true }}
                >
                    <IconMap />
                    Request a feature
                </Link>
                <Link targetBlankIcon to="https://posthog.com/changelog" buttonProps={{ menuItem: true }}>
                    <IconLive />
                    Change log
                </Link>
            </PopoverPrimitiveContent>
        </PopoverPrimitive>
    )
}
