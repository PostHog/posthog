import clsx from 'clsx'
import React from 'react'

import { IconSparkles, IconWrench } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { AnimatedSparkles } from './components/AnimatedSparkles'
import { ToolRegistration } from './max-constants'
import { useMaxTool } from './useMaxTool'

interface MaxToolProps extends Omit<ToolRegistration, 'name' | 'description'> {
    /** The child element(s) that will be wrapped by this component */
    children: React.ReactElement | (({ toolAvailable }: { toolAvailable: boolean }) => React.ReactElement)
    /** Whether MaxTool functionality is active. When false, just renders children without MaxTool wrapper. */
    active?: boolean
    initialMaxPrompt?: string
    onMaxOpen?: () => void
    className?: string
    position?: 'top-right' | 'bottom-right' | 'top-left' | 'bottom-left'
}

export function MaxTool({
    identifier,
    context,
    introOverride,
    callback,
    suggestions,
    children: Children,
    active = true,
    initialMaxPrompt,
    onMaxOpen,
    className,
    position = 'top-right',
}: MaxToolProps): JSX.Element {
    const { definition, isMaxOpen, openMax } = useMaxTool({
        identifier,
        context,
        introOverride,
        callback,
        suggestions,
        active,
        initialMaxPrompt,
        onMaxOpen,
    })

    let content: JSX.Element
    if (!definition) {
        content = <>{typeof Children === 'function' ? <Children toolAvailable={false} /> : Children}</>
    } else {
        content = (
            <>
                <Tooltip
                    title={
                        !isMaxOpen ? (
                            <>
                                <IconSparkles className="mr-1.5" />
                                {definition.name} with PostHog AI
                            </>
                        ) : (
                            <>
                                PostHog AI can use this tool
                                <br />
                                {definition.icon || <IconWrench />}
                                <i className="ml-1.5">{definition.name}</i>
                            </>
                        )
                    }
                    placement="top-end"
                    delayMs={0}
                >
                    <button
                        className={clsx(
                            'absolute z-10 transition duration-50 cursor-pointer -scale-x-100 hover:scale-y-110 hover:-scale-x-110 rounded-lg border border-dashed border-accent size-7 backdrop-blur-[2px] bg-[rgba(255,255,255,0.5)] dark:bg-[rgba(0,0,0,0.5)]',
                            position === 'top-right' && '-top-2 -right-2',
                            position === 'bottom-right' && '-bottom-2 -right-2',
                            position === 'top-left' && '-top-2 -left-2',
                            position === 'bottom-left' && '-bottom-2 -left-2'
                        )}
                        type="button"
                        onClick={openMax || undefined}
                    >
                        <AnimatedSparkles className="relative size-full pl-0.5 pb-0.5" />
                    </button>
                </Tooltip>
                {typeof Children === 'function' ? <Children toolAvailable={true} /> : Children}
            </>
        )
    }
    return (
        <div
            className={clsx(
                'relative flex flex-col',
                // Rounding is +1px to account for the border
                isMaxOpen &&
                    active &&
                    'border border-primary-3000 border-dashed -m-px rounded-[calc(var(--radius)+1px)]',
                className
            )}
        >
            {content}
        </div>
    )
}

export default MaxTool
