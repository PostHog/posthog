import clsx from 'clsx'
import { useValues } from 'kea'
import React from 'react'

import { IconSparkles, IconWrench } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { userLogic } from 'scenes/userLogic'

import { ToolRegistration } from './max-constants'
import { useMaxTool } from './useMaxTool'
import { generateBurstPoints } from './utils'

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
    icon,
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
    const { user } = useValues(userLogic)

    const { definition, isMaxOpen, openMax } = useMaxTool({
        identifier,
        icon,
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
                                {definition.name} with Max
                            </>
                        ) : (
                            <>
                                Max can use this tool
                                <br />
                                {icon || <IconWrench />}
                                <i className="ml-1.5">{definition.name}</i>
                            </>
                        )
                    }
                    placement="top-end"
                    delayMs={0}
                >
                    <button
                        className={clsx(
                            'absolute z-10 transition duration-50 cursor-pointer -scale-x-100 hover:scale-y-110 hover:-scale-x-110',
                            position === 'top-right' && '-top-2 -right-2',
                            position === 'bottom-right' && '-bottom-2 -right-2',
                            position === 'top-left' && '-top-2 -left-2',
                            position === 'bottom-left' && '-bottom-2 -left-2'
                        )}
                        type="button"
                        onClick={openMax || undefined}
                    >
                        {/* Burst border - the inset and size vals are very specific just bc these look nice */}
                        <svg className={clsx('absolute -inset-1 size-8')} viewBox="0 0 100 100">
                            <polygon points={generateBurstPoints(16, 3 / 16)} fill="var(--primary-3000)" />
                        </svg>
                        <ProfilePicture
                            user={{ hedgehog_config: { ...user?.hedgehog_config, use_as_profile: true } }}
                            size="md"
                            className="bg-bg-light"
                        />
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
                isMaxOpen && 'border border-primary-3000 border-dashed -m-px rounded-[calc(var(--radius)+1px)]',
                className
            )}
        >
            {content}
        </div>
    )
}

export default MaxTool
