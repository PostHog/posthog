import './YearInHogButton.scss'

import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { HeartHog } from 'lib/components/hedgehogs'
import { IconXmasTree } from 'lib/lemon-ui/icons'
import { useState } from 'react'

export function YearInHogButton({ url }: { url: string | null }): JSX.Element | null {
    const [isHovering, setIsHovering] = useState<boolean | null>(null)
    return url ? (
        <div className="relative">
            <HeartHog
                width="36"
                height="36"
                className={clsx(
                    'CheekyHog',
                    isHovering && 'CheekyHog--peek',
                    isHovering === false && 'CheekyHog--hide'
                )}
            />
            <div className="absolute top-0 left-0 w-full h-full YearInHog__mask" />
            <LemonButton
                icon={<IconXmasTree />}
                type="secondary"
                to={url}
                targetBlank={true}
                size="small"
                onMouseEnter={() => setIsHovering(true)}
                onMouseLeave={() => setIsHovering(false)}
            >
                PostHog Unwrapped
            </LemonButton>
        </div>
    ) : null
}
