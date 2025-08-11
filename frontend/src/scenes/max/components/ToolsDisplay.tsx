import { IconCheck, IconX, IconWrench, IconInfo, IconArrowRight } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { ReactNode, useState, useRef, useEffect } from 'react'
import React from 'react'

import { useResizeObserver } from '~/lib/hooks/useResizeObserver'

import { ToolDefinition, TOOL_DEFINITIONS, ToolRegistration } from '../maxGlobalLogic'
import './QuestionInput.scss'
import { AssistantContextualTool } from '~/queries/schema/schema-assistant-messages'
import { identifierToHuman } from 'lib/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

export const MAX_GENERALLY_CAN = ['See and analyze attached context'] as const

export const MAX_GENERALLY_CANNOT = [
    'Access your infrastructure, source code, or third‑party tools',
    'Browse the web beyond PostHog documentation',
    'See data outside this PostHog project',
    'Guarantee correctness of the queries created',
    'Order tungsten cubes',
] as const

export interface ToolsDisplayProps {
    isFloating?: boolean
    tools: ToolRegistration[]
    bottomActions?: ReactNode
}

export const ToolsDisplay: React.FC<ToolsDisplayProps> = ({ isFloating, tools, bottomActions }) => {
    const { featureFlags } = useValues(featureFlagLogic)

    const toolsContainerRef = useRef<HTMLDivElement>(null)
    const toolsRef = useRef<HTMLElement[]>([])
    const [firstToolOverflowing, setFirstToolOverflowing] = useState<AssistantContextualTool | null>(null)

    function onResize(): void {
        let foundOverflow = false
        for (let i = 0; i < toolsRef.current.length; i++) {
            const toolEl = toolsRef.current[i]
            if (toolEl) {
                const rightOverflow =
                    toolEl.getBoundingClientRect().right - toolEl.parentElement!.getBoundingClientRect().right
                // Items other than the last one need 56px free space to the right to safely show "+ n more"
                const freeSpaceRequirementPx = i < toolsRef.current.length - 1 ? 56 : 0
                if (rightOverflow > -freeSpaceRequirementPx) {
                    setFirstToolOverflowing(tools[tools.length - i - 1].identifier)
                    foundOverflow = true
                    break
                }
            }
        }
        if (!foundOverflow) {
            setFirstToolOverflowing(null)
        }
    }

    useEffect(() => {
        onResize()
    }, [tools.map((t) => t.name).join(';'), onResize])
    useResizeObserver({ ref: toolsContainerRef, onResize })

    // We show the tools reversed, so the ones registered last (scene-specific) are shown first
    const toolsInReverse = tools.toReversed()
    const toolsHidden = firstToolOverflowing
        ? toolsInReverse
              .slice(toolsInReverse.findIndex((tool) => tool.identifier === firstToolOverflowing))
              .map((tool) => tool.identifier)
        : []

    /** Dynamic list of things Max can do right now, i.e. general capabilities + tools registered. */
    const maxCanHere = [
        ...toolsInReverse.map((tool) => (
            <>
                <strong>{tool.name}</strong>
                {tool.description?.replace(tool.name, '')}
            </>
        )),
        ...MAX_GENERALLY_CAN,
    ]
    /** Dynamic list of things Max can do elsewhere in PostHog, by product. */
    const maxCanElsewhereByProduct = Object.entries(TOOL_DEFINITIONS)
        .filter(
            ([_, tool]) =>
                !tools.find((registeredTool) => registeredTool.name === tool.name) &&
                (!tool.flag || featureFlags[tool.flag])
        )
        .reduce(
            (acc, [_, tool]) => {
                if (!tool.product) {
                    console.warn(`Unexpected: Global Max tool ${tool.name} appears not to be registered`)
                    return acc
                }
                if (!acc[tool.product]) {
                    acc[tool.product] = []
                }
                acc[tool.product || 'GLOBAL']!.push(tool)
                return acc
            },
            {} as Partial<Record<Scene, ToolDefinition[]>>
        )
    /** Dynamic list of things Max can do elsewhere in PostHog, by product. */
    const maxCanElsewhere = Object.entries(maxCanElsewhereByProduct).map(([product, tools]) => (
        <>
            <em>In {sceneConfigurations[product]?.name || identifierToHuman(product)}: </em>
            {tools.map((tool, index) => (
                <React.Fragment key={index}>
                    <strong>{tool.name}</strong>
                    {tool.description?.replace(tool.name, '')}
                    {index < tools.length - 1 && <>; </>}
                </React.Fragment>
            ))}
        </>
    ))

    return (
        <div ref={toolsContainerRef} className="flex items-center w-full justify-center cursor-default">
            <Tooltip
                placement="bottom-end"
                arrowOffset={6 /* 6px from right edge to align with the info icon */}
                delayMs={50}
                title={
                    <>
                        <div className="mb-2">
                            <div className="font-semibold mb-0.5">Max can:</div>
                            <ul className="space-y-0.5 text-sm *:flex *:items-start">
                                {maxCanHere.map((item, index) => (
                                    <li key={index}>
                                        <IconCheck className="text-base text-success shrink-0 ml-1 mr-2" />
                                        <span>{item}</span>
                                    </li>
                                ))}
                                {maxCanElsewhere.map((item, index) => (
                                    <li key={index}>
                                        <IconArrowRight className="text-base text-warning shrink-0 ml-1 mr-2" />
                                        <span>{item}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                        <div>
                            <div className="font-semibold mb-0.5">Max can't (yet):</div>
                            <ul className="space-y-0.5 text-sm *:flex *:items-start">
                                {MAX_GENERALLY_CANNOT.map((item, index) => (
                                    <li key={index}>
                                        <IconX className="text-base text-danger shrink-0 ml-1 mr-2" />
                                        <span>{item}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    </>
                }
            >
                <div
                    className={clsx(
                        'relative flex items-center text-xs font-medium justify-between gap-1 pl-1',
                        !isFloating
                            ? 'w-[calc(100%-1rem)] py-0.75 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                            : `w-full pb-1`
                    )}
                >
                    <div className="w-full flex items-center gap-1 overflow-hidden">
                        <span className="shrink-0">Tools available:</span>
                        {toolsInReverse.map((tool, index) => (
                            <React.Fragment key={tool.identifier}>
                                <span
                                    ref={(e) => e && (toolsRef.current[index] = e)}
                                    className="relative flex-shrink-0"
                                >
                                    {/* We're using --color-posthog-3000-300 instead of border-primary (--color-posthog-3000-200)
                                or border-secondary (--color-posthog-3000-400) because the former is almost invisible here, and the latter too distinct */}
                                    <ToolPill
                                        tool={tool}
                                        hidden={toolsHidden.includes(tool.identifier)}
                                        className="border-[var(--color-posthog-3000-300)]"
                                    />
                                    {tool.identifier === firstToolOverflowing && (
                                        <span className="absolute left-0 top-0 bottom-0 text-xs text-muted-foreground flex items-center gap-1">
                                            + {toolsHidden.length} more
                                        </span>
                                    )}
                                </span>
                            </React.Fragment>
                        ))}
                    </div>
                    <IconInfo className="text-sm p-1 box-content z-10" />
                </div>
            </Tooltip>
            {bottomActions && <div className="ml-auto">{bottomActions}</div>}
        </div>
    )
}

function ToolPill({
    tool,
    hidden,
    className,
}: {
    tool: ToolRegistration
    hidden?: boolean
    className?: string
}): JSX.Element {
    return (
        <em
            className={clsx(
                'relative inline-flex items-center gap-1 border border-dashed rounded-sm pl-0.5 pr-1',
                hidden && 'invisible',
                className
            )}
        >
            <span className="text-sm">{tool.icon || <IconWrench />}</span>
            {tool.name}
        </em>
    )
}
