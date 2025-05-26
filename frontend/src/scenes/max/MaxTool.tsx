import { IconSparkles } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconTools } from 'lib/lemon-ui/icons'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import React, { useEffect } from 'react'
import { userLogic } from 'scenes/userLogic'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { maxGlobalLogic, ToolDefinition } from './maxGlobalLogic'

interface MaxToolProps extends ToolDefinition {
    /** The child element(s) that will be wrapped by this component */
    children: React.ReactElement | (({ toolAvailable }: { toolAvailable: boolean }) => React.ReactElement)
    initialMaxPrompt?: string
    onMaxOpen?: () => void
}

function generateBurstPoints(spikeCount: number, spikiness: number): string {
    if (spikiness < 0 || spikiness > 1) {
        throw new Error('Spikiness must be between 0 and 1')
    }
    if (spikeCount < 1) {
        throw new Error('Spikes must be at least 1')
    }

    let points = ''
    const outerRadius = 50
    const innerRadius = 50 * (1 - spikiness)

    for (let i = 0; i < spikeCount * 2; i++) {
        const radius = i % 2 === 0 ? outerRadius : innerRadius
        const angle = (Math.PI * i) / spikeCount
        const x = 50 + radius * Math.cos(angle)
        const y = 50 + radius * Math.sin(angle)
        points += `${x},${y} `
    }

    return points.trim()
}

export function MaxTool({
    name,
    displayName,
    context,
    introOverride,
    callback,
    children: Children,
    initialMaxPrompt,
    onMaxOpen,
}: MaxToolProps): JSX.Element {
    const { registerTool, deregisterTool } = useActions(maxGlobalLogic)
    const { user } = useValues(userLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)

    const isMaxAvailable = useFeatureFlag('ARTIFICIAL_HOG')
    const isMaxOpen = isMaxAvailable && sidePanelOpen && selectedTab === SidePanelTab.Max

    useEffect(() => {
        registerTool({ name, displayName, context, introOverride, callback })
        return () => {
            deregisterTool(name)
        }
    }, [name, displayName, JSON.stringify(context), introOverride, callback, registerTool, deregisterTool])

    let content: JSX.Element
    if (!isMaxAvailable) {
        content = <>{typeof Children === 'function' ? <Children toolAvailable={false} /> : Children}</>
    } else {
        content = (
            <>
                <Tooltip
                    title={
                        !isMaxOpen ? (
                            <>
                                <IconSparkles className="mr-1.5" />
                                {displayName} with Max
                            </>
                        ) : (
                            <>
                                Max can use this tool
                                <br />
                                <IconTools className="mr-1.5" />
                                <i>{displayName}</i>
                            </>
                        )
                    }
                    placement="top-end"
                    delayMs={0}
                >
                    <button
                        className="absolute -top-2 -right-2 z-10 transition duration-50 cursor-pointer -scale-x-100 hover:scale-y-110 hover:-scale-x-110"
                        type="button"
                        onClick={() => {
                            openSidePanel(SidePanelTab.Max, initialMaxPrompt)
                            onMaxOpen?.()
                        }}
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
                'relative',
                // Rounding is +1px to account for the border
                isMaxOpen && 'border border-primary-3000 border-dashed -m-px rounded-[calc(var(--radius)+1px)]'
            )}
        >
            {content}
        </div>
    )
}

export default MaxTool
