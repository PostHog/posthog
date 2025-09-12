import { IconChevronRight } from '@posthog/icons'
import { LemonCollapse } from '@posthog/lemon-ui'

import { isValidRegexp } from 'lib/utils/regexp'

import { PathCleaningFilter } from '~/types'

import { parseAliasToReadable } from './PathCleanFilterItem'

interface ProcessingStep {
    stepNumber: number
    filter: PathCleaningFilter
    inputPath: string
    outputPath: string
    wasModified: boolean
    isValidRegex: boolean
}

interface PathCleaningRulesDebuggerProps {
    testPath: string
    filters: PathCleaningFilter[]
    finalResult: JSX.Element | JSX.Element[] | string | null
}

const cleanPathWithDebugSteps = (path: string, filters: PathCleaningFilter[]): ProcessingStep[] => {
    const steps: ProcessingStep[] = []
    let currentPath = path

    filters.forEach((filter, index) => {
        const isValidRegex = isValidRegexp(filter.regex ?? '')
        let outputPath = currentPath

        if (isValidRegex) {
            outputPath = currentPath.replace(new RegExp(filter.regex ?? '', 'gi'), filter.alias ?? '')
        }

        steps.push({
            stepNumber: index + 1,
            filter,
            inputPath: currentPath,
            outputPath,
            wasModified: currentPath !== outputPath,
            isValidRegex,
        })

        currentPath = outputPath
    })

    return steps
}

export function PathCleaningRulesDebugger({
    testPath,
    filters,
    finalResult,
}: PathCleaningRulesDebuggerProps): JSX.Element | null {
    const debugSteps = cleanPathWithDebugSteps(testPath, filters)

    return (
        <div className="mt-3">
            <LemonCollapse
                panels={[
                    {
                        key: 'debug',
                        header: 'Debug: Step-by-step processing',
                        content: (
                            <div className="space-y-1">
                                {/* Column Headers */}
                                <div className="flex gap-3 items-center py-2 px-3 text-xs font-medium text-muted-alt border-b bg-accent-3000">
                                    <div
                                        className="w-8 flex-shrink-0 text-center"
                                        title="Rule number in processing order"
                                    >
                                        #
                                    </div>
                                    <div className="flex-1 min-w-0" title="Regex pattern and replacement alias">
                                        Pattern → Alias
                                    </div>
                                    <div className="flex-1 min-w-0" title="Path after this rule is applied">
                                        Output
                                    </div>
                                    <div
                                        className="w-6 flex-shrink-0 flex justify-center"
                                        title="Whether this rule matched and modified the path"
                                    >
                                        ✓
                                    </div>
                                </div>

                                {debugSteps.map((step) => (
                                    <div
                                        key={step.stepNumber}
                                        className="flex gap-3 items-center px-3 text-xs hover:bg-accent-light border-b border-border"
                                    >
                                        <div className="w-8 flex-shrink-0 text-center text-muted-alt font-medium">
                                            {step.stepNumber}
                                        </div>
                                        <div className="flex-1 min-w-0 flex items-center gap-2">
                                            <code
                                                className={`font-mono text-xs px-2 py-1 rounded flex-shrink-0 max-w-32 overflow-hidden text-ellipsis whitespace-nowrap ${
                                                    step.isValidRegex
                                                        ? 'bg-accent-light text-accent'
                                                        : 'bg-danger-light text-danger'
                                                }`}
                                                title={step.filter.regex || '(Empty)'}
                                            >
                                                {step.filter.regex || '(Empty)'}
                                            </code>
                                            <IconChevronRight className="text-muted-alt h-3 w-3 flex-shrink-0" />
                                            <span
                                                className="font-mono text-xs min-w-0 overflow-hidden text-ellipsis whitespace-nowrap"
                                                title={step.filter.alias || '(Empty)'}
                                            >
                                                {parseAliasToReadable(step.filter.alias || '(Empty)')}
                                            </span>
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <span
                                                className="font-mono text-xs block overflow-hidden text-ellipsis whitespace-nowrap"
                                                title={step.outputPath}
                                            >
                                                {parseAliasToReadable(step.outputPath)}
                                            </span>
                                        </div>
                                        <div className="w-6 flex-shrink-0 flex justify-center">
                                            {step.wasModified ? (
                                                <div
                                                    className="w-2 h-2 rounded-full bg-success"
                                                    title="Matched and modified"
                                                />
                                            ) : (
                                                <div
                                                    className="w-2 h-2 rounded-full bg-muted-alt"
                                                    title="No match, unchanged"
                                                />
                                            )}
                                        </div>
                                    </div>
                                ))}

                                <div className="flex gap-3 items-center py-3 px-3 bg-primary-light border border-primary rounded mt-3">
                                    <div className="w-20 flex-shrink-0 text-xs font-medium text-primary">
                                        Final result:
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <code
                                            className="font-mono text-xs text-primary block overflow-hidden text-ellipsis whitespace-nowrap"
                                            title={String(finalResult)}
                                        >
                                            {finalResult}
                                        </code>
                                    </div>
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
