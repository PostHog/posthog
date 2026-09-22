#!/usr/bin/env ts-node
;['.scss', '.css', '.svg', '.png', '.jpg', '.jpeg', '.gif'].forEach((ext) => {
    require.extensions[ext] = () => {}
})

import * as fs from 'fs'
import * as path from 'path'

import { SURVEY_SDK_REQUIREMENTS, SurveySdkType } from '../../src/scenes/surveys/surveyVersionRequirements'

const SDK_INFO: Record<SurveySdkType, { name: string; docsUrl: string }> = {
    'posthog-js': { name: 'JavaScript Web', docsUrl: '/docs/libraries/js' },
    'posthog-react-native': { name: 'React Native', docsUrl: '/docs/libraries/react-native' },
    'posthog-ios': { name: 'iOS', docsUrl: '/docs/libraries/ios' },
    'posthog-android': { name: 'Android', docsUrl: '/docs/libraries/android' },
    posthog_flutter: { name: 'Flutter', docsUrl: '/docs/libraries/flutter' },
}

const SDK_ORDER: SurveySdkType[] = [
    'posthog-js',
    'posthog-react-native',
    'posthog-ios',
    'posthog-android',
    'posthog_flutter',
]

const SDK_SUPPORT_NOTES = `## Android survey UI

The Android versions in the table refer to \`posthog-android\`.
The built-in survey UI also requires \`posthog-android-surveys-compose\` 0.2.2+ for choice shuffling, 0.3.0+ for auto-submit, and 0.4.0+ for persistent resume.
Custom survey delegates must implement these UI behaviors themselves.

## Partial responses and resume

Partial response collection saves submitted answers after each question when enabled for the survey.
React Native 4.75.0+, iOS 3.79.0+, and Android 3.70.0+ can also restore unfinished surveys after an app restart, including saved answers and the next question.
Completion, dismissal, SDK reset, and incompatible survey changes clear saved progress.
Custom iOS delegates must opt in with \`supportsSurveyResume\` and honor \`initialQuestionIndex\`; custom Android delegates must implement \`PostHogSurveysResumeAwareDelegate\`.

Flutter does not yet support persistent resume.
Partial response collection depends on the resolved native SDK: iOS 3.79.0+ or Android 3.70.0+.
Flutter 5.45.0 permits older native versions, so its version alone does not guarantee partial response support.
The same limitation applies to feature flag variant targeting, which requires iOS 3.78.0+ or Android 3.67.0+.
The Flutter cells remain marked as not yet supported until the SDK guarantees these native dependencies.

## Selection behavior

Choice option shuffling is available for single-choice and multiple-choice questions in all five SDKs listed above.
The open-ended "Other" option stays last, and the choice order stays stable while the user answers.
Auto-submit applies to ratings and single-choice questions without an open-ended choice.
Multiple-choice questions and questions with an open-ended choice keep the submit button.

## Cancellation events

Cancellation events remove a survey from the event-triggered display queue when a configured event occurs.
They are separate from the dismissal event emitted when a user closes a survey.
Cancellation events remain available only in the JavaScript Web SDK.`

function generateMarkdown(): string {
    const lines: string[] = [
        '---',
        'title: SDK feature support',
        'sidebar: Docs',
        'showTitle: true',
        '---',
        '',
        "import { IconCheck, IconWrench, IconX } from '@posthog/icons'",
        '',
        'Not all survey features are available on every SDK. Web has the most complete support, while mobile SDKs have some limitations.',
        '',
        'For setup instructions, see the [installation guides](/docs/surveys/installation).',
        '',
    ]

    const headerCells = ['Feature', ...SDK_ORDER.map((sdk) => `[${SDK_INFO[sdk].name}](${SDK_INFO[sdk].docsUrl})`)]

    // Build all data rows first to calculate column widths
    const dataRows: string[][] = []
    for (const req of SURVEY_SDK_REQUIREMENTS) {
        const cells: string[] = [req.feature]

        for (const sdk of SDK_ORDER) {
            const minVersion = req.sdkVersions[sdk]
            const unsupported = req.unsupportedSdks.find((u) => u.sdk === sdk)

            if (minVersion) {
                cells.push(`<IconCheck className="w-4 h-4 inline text-green" /> ${minVersion}+`)
            } else if (unsupported) {
                if (unsupported.issue === false) {
                    cells.push(`<IconX className="w-4 h-4 inline text-red" />`)
                } else {
                    cells.push(
                        `<a href="${unsupported.issue}"><IconWrench className="w-4 h-4 inline text-muted" /></a>`
                    )
                }
            } else {
                cells.push('—')
            }
        }

        dataRows.push(cells)
    }

    // Calculate column widths (max of header and all data cells)
    const colWidths = headerCells.map((header, i) => {
        const dataMax = Math.max(...dataRows.map((row) => row[i].length))
        return Math.max(header.length, dataMax)
    })

    // Format rows with padding
    const formatRow = (cells: string[]): string =>
        '| ' + cells.map((cell, i) => cell.padEnd(colWidths[i])).join(' | ') + ' |'

    lines.push(formatRow(headerCells))
    lines.push('| ' + colWidths.map((w) => '-'.repeat(w)).join(' | ') + ' |')

    for (const row of dataRows) {
        lines.push(formatRow(row))
    }

    lines.push('', SDK_SUPPORT_NOTES)

    return lines.join('\n')
}

const outputPath = path.resolve(__dirname, '../../../docs/published/docs/surveys/sdk-feature-support.mdx')
const content = generateMarkdown()

fs.writeFileSync(outputPath, content + '\n', 'utf-8')
