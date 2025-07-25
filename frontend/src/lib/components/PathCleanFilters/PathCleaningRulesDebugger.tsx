import { LemonCollapse } from '@posthog/lemon-ui'
import { IconChevronRight } from '@posthog/icons'
import { parseAliasToReadable } from './PathCleanFilterItem'
import { isValidRegexp } from 'lib/utils/regexp'
import { PathCleaningFilter } from '~/types'

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
        <div className="mt-4">
            <LemonCollapse
                panels={[
                    {
                        key: 'debug',
                        header: 'Debug: Step-by-step processing',
                        content: (
                            <div className="space-y-3">
                                {debugSteps.map((step) => (
                                    <div key={step.stepNumber} className="flex items-center gap-2 p-2 border rounded">
                                        <div className="flex items-center gap-2 flex-1">
                                            <span className="text-sm font-semibold text-muted-alt w-16">
                                                Rule {step.stepNumber}:
                                            </span>
                                            <div className="flex items-center gap-2 flex-1">
                                                <code
                                                    className={`font-mono text-sm px-2 py-1 rounded ${
                                                        step.isValidRegex
                                                            ? 'bg-accent-light text-accent'
                                                            : 'bg-red-50 text-danger border border-danger'
                                                    }`}
                                                >
                                                    {step.filter.regex || '(Empty)'}
                                                </code>
                                                <IconChevronRight className="text-muted-alt" />
                                                <span className="font-mono text-sm">
                                                    {parseAliasToReadable(step.filter.alias || '(Empty)')}
                                                </span>
                                            </div>
                                        </div>
                                        <div className="flex items-center flex-1 gap-2">
                                            <span className="text-sm font-semibold text-muted-alt w-16">Output:</span>
                                            <span className="font-mono text-sm">
                                                {parseAliasToReadable(step.outputPath)}
                                            </span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            {step.wasModified ? (
                                                <span className="text-xs text-success font-semibold bg-green-100 px-2 py-1 rounded">
                                                    MATCHED
                                                </span>
                                            ) : (
                                                <span className="text-xs text-muted-alt font-semibold bg-gray-100 px-2 py-1 rounded">
                                                    NO MATCH
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                ))}

                                <div className="flex items-center gap-2 p-2 bg-blue-50 rounded border border-blue-200">
                                    <span className="text-sm font-semibold text-blue-700">Final result:</span>
                                    <code className="font-mono text-sm text-blue-800">{finalResult}</code>
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
