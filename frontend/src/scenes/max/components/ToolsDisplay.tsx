import { IconCheck, IconX, IconWrench, IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import {} from 'kea'
import { ReactNode, useState, useRef } from 'react'
import React from 'react'

import { useResizeObserver } from '~/lib/hooks/useResizeObserver'

import { ToolDefinition } from '../maxGlobalLogic'
import './QuestionInput.scss'
import { AssistantContextualTool } from '~/queries/schema/schema-assistant-messages'

export const MAX_CAN = [
    'Query your analytics data and data warehouse',
    'Answer questions from PostHog docs',
    'Navigate to relevant places in PostHog',
    'Read and analyze attached context like dashboards, insights, and more',
    <>
        <em>In Insights:</em> Edit the currently-viewed insight
    </>,
    <>
        <em>In SQL editor:</em> Write and tweak HogQL queries
    </>,
    <>
        <em>In Session replay:</em> Search session recordings
    </>,
    <>
        <em>In Surveys:</em> Create surveys
    </>,
    <>
        <em>In Data pipelines:</em> Set up pipeline transformations and filters, using Hog
    </>,
] as const

export const MAX_CANNOT = [
    'Access your infrastructure, source code, or third‑party tools',
    'Browse the web beyond PostHog documentation',
    'See data outside this PostHog project',
    'Guarantee correctness of the queries created',
    'Order tungsten cubes',
] as const

export interface ToolsDisplayProps {
    isFloating?: boolean
    tools: ToolDefinition[]
    bottomActions?: ReactNode
}

export const ToolsDisplay: React.FC<ToolsDisplayProps> = ({ isFloating, tools, bottomActions }) => {
    const toolsContainerRef = useRef<HTMLDivElement>(null)
    const toolsRef = useRef<HTMLElement[]>([])
    const [firstToolOverflowing, setFirstToolOverflowing] = useState<AssistantContextualTool | null>(null)

    useResizeObserver({
        ref: toolsContainerRef,
        onResize: () => {
            let foundOverflow = false
            for (let i = 0; i < toolsRef.current.length; i++) {
                const toolEl = toolsRef.current[i]
                if (toolEl) {
                    const rightOverflow =
                        toolEl.getBoundingClientRect().right - toolEl.parentElement!.getBoundingClientRect().right
                    // Items other than the last one need 60px free space to the right to safely show "+ n more"
                    const freeSpaceRequirementPx = i < toolsRef.current.length - 1 ? 60 : 0
                    if (rightOverflow > -freeSpaceRequirementPx) {
                        setFirstToolOverflowing(tools[tools.length - i - 1].name)
                        foundOverflow = true
                        break
                    }
                }
            }
            if (!foundOverflow) {
                setFirstToolOverflowing(null)
            }
        },
    })

    // We show the tools reversed, so the ones registered last (scene-specific) are shown first
    const toolsInReverse = tools.toReversed()
    const toolsHidden = firstToolOverflowing
        ? toolsInReverse
              .slice(toolsInReverse.findIndex((tool) => tool.name === firstToolOverflowing))
              .map((tool) => tool.name)
        : []

    return (
        <div ref={toolsContainerRef} className="flex items-center w-full justify-center cursor-default">
            <div
                className={clsx(
                    'relative flex items-center text-xs font-medium justify-between gap-1 pl-1',
                    !isFloating
                        ? 'w-[calc(100%-1rem)] py-0.75 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                        : `w-full pb-1`
                )}
            >
                <div className="w-full flex items-center gap-1">
                    <span className="shrink-0">Tools available:</span>
                    {toolsInReverse.map((tool, index) => (
                        <React.Fragment key={tool.name}>
                            <span ref={(e) => e && (toolsRef.current[index] = e)} className="relative flex-shrink-0">
                                {/* We're using --color-posthog-3000-300 instead of border-primary (--color-posthog-3000-200)
                                or border-secondary (--color-posthog-3000-400) because the former is almost invisible here, and the latter too distinct */}
                                <ToolPill
                                    tool={tool}
                                    hidden={toolsHidden.includes(tool.name)}
                                    className="border-[var(--color-posthog-3000-300)]"
                                />
                                {tool.name === firstToolOverflowing && (
                                    <Tooltip
                                        title={
                                            <div className="flex items-center gap-1 flex-wrap">
                                                {tools
                                                    .filter((t) => toolsHidden.includes(t.name))
                                                    .map((t) => (
                                                        <ToolPill
                                                            key={t.name}
                                                            tool={t}
                                                            className="border-[var(--color-neutral-500)]"
                                                        />
                                                    ))}
                                            </div>
                                        }
                                    >
                                        <span className="absolute left-0 top-0 bottom-0 text-xs text-muted-foreground flex items-center gap-1 cursor-help">
                                            + {toolsHidden.length} more
                                        </span>
                                    </Tooltip>
                                )}
                            </span>
                        </React.Fragment>
                    ))}
                </div>
                <Tooltip
                    placement="bottom-end"
                    arrowOffset={6 /* 6px from right edge to align with the info icon */}
                    delayMs={50}
                    title={
                        <>
                            <div className="mb-2">
                                <div className="font-semibold mb-0.5">Max can:</div>
                                <ul className="space-y-0.5 text-sm">
                                    {MAX_CAN.map((item, index) => (
                                        <li key={index} className="flex items-center">
                                            <IconCheck className="text-base text-success shrink-0 ml-1 mr-2" />
                                            <span>{item}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                            <div>
                                <div className="font-semibold mb-0.5">Max can't (yet):</div>
                                <ul className="space-y-0.5 text-sm">
                                    {MAX_CANNOT.map((item, index) => (
                                        <li key={index} className="flex items-center">
                                            <IconX className="text-base text-danger shrink-0 ml-1 mr-2" />
                                            <span>{item}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        </>
                    }
                >
                    <IconInfo className="text-sm p-1 box-content z-10" />
                </Tooltip>
            </div>
            {bottomActions && <div className="ml-auto">{bottomActions}</div>}
        </div>
    )
}

function ToolPill({
    tool,
    hidden,
    className,
}: {
    tool: ToolDefinition
    hidden?: boolean
    className?: string
}): JSX.Element {
    return (
        <Tooltip key={tool.name} title={tool.description}>
            <em
                className={clsx(
                    'relative inline-flex items-center gap-1 border border-dashed rounded-sm pl-0.5 pr-1 cursor-help',
                    hidden && 'invisible',
                    className
                )}
            >
                <span className="text-sm">{tool.icon || <IconWrench />}</span>
                {tool.displayName}
            </em>
        </Tooltip>
    )
}
