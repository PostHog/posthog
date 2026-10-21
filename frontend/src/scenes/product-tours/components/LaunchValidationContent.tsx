import { IconCode, IconCursorClick, IconDocument } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LaunchValidationIssue, LaunchValidationIssueType } from '../productTourLogic'

const ISSUE_CONFIG: Record<
    LaunchValidationIssueType,
    { icon: JSX.Element; label: string; instruction: string; docsLink?: string }
> = {
    missing_element: {
        icon: <IconCursorClick />,
        label: 'Missing target element',
        instruction:
            'Click "Select element in Toolbar" to choose an element on your page, or "Remove element" to position the step as a simple pop-up.',
        docsLink: 'https://posthog.com/docs/product-tours/element-selection#automatic-element-targeting',
    },
    missing_selector: {
        icon: <IconCode />,
        label: 'Missing CSS selector',
        instruction:
            'Enter a CSS selector in the step settings, or click "Remove element" to position the step as a simple pop-up.',
        docsLink: 'https://posthog.com/docs/product-tours/element-selection#manual-element-targeting',
    },
}

function formatStepList(stepNumbers: number[]): string {
    if (stepNumbers.length === 1) {
        return `Step ${stepNumbers[0]}`
    }
    return `Steps ${stepNumbers.slice(0, -1).join(', ')} and ${stepNumbers[stepNumbers.length - 1]}`
}

export function LaunchValidationContent({ issues }: { issues: LaunchValidationIssue[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {issues.map((issue) => {
                const config = ISSUE_CONFIG[issue.type]
                return (
                    <div
                        key={issue.type}
                        className="flex items-start gap-3 p-3 rounded-lg bg-warning-highlight border border-warning"
                    >
                        <span className="text-warning text-lg mt-0.5">{config.icon}</span>
                        <div className="flex flex-col items-start gap-2">
                            <div className="flex flex-col gap-0.5 text-sm">
                                <span className="font-medium">
                                    {formatStepList(issue.stepNumbers)}: {config.label}
                                </span>
                                <span className="text-muted">{config.instruction}</span>
                            </div>
                            {config.docsLink && (
                                <LemonButton
                                    size="small"
                                    type="primary"
                                    icon={<IconDocument />}
                                    targetBlank
                                    to={config.docsLink}
                                >
                                    Read the docs
                                </LemonButton>
                            )}
                        </div>
                    </div>
                )
            })}
        </div>
    )
}
