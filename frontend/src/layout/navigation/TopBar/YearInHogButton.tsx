import { HeartHog } from 'lib/components/hedgehogs'
import { LemonButton } from 'lib/components/LemonButton'
import { XmasTree } from 'lib/components/icons'
import { useState } from 'react'
import clsx from 'clsx'

export function YearInHogButton({ url }: { url: string | null }): JSX.Element | null {
    const [isHovering, setIsHovering] = useState<boolean | null>(null)
    return url ? (
        <div className={'relative'}>
            <HeartHog
                width={'36'}
                height={'36'}
                className={clsx(
                    'CheekyHog',
                    isHovering && 'CheekyHog--peek',
                    isHovering === false && 'CheekyHog--hide'
                )}
            />
            <LemonButton
                icon={<XmasTree />}
                type={'secondary'}
                status={'orange'}
                to={url}
                targetBlank={true}
                size={'small'}
                onMouseEnter={() => setIsHovering(true)}
                onMouseLeave={() => setIsHovering(false)}
            >
                Year in PostHog
            </LemonButton>
        </div>
    ) : null
}
