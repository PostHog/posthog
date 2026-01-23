#!/usr/bin/env ts-node
;['.scss', '.css', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.lottie'].forEach((ext) => {
    require.extensions[ext] = () => {}
})

import * as fs from 'fs'
import * as path from 'path'

import { SURVEY_SDK_REQUIREMENTS, SurveySdkType } from '../src/scenes/surveys/surveyVersionRequirements'

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

function generateMarkdown(): string {
    const lines: string[] = [
        '---',
        'title: SDK feature support',
        'sidebar: Docs',
        'showTitle: true',
        '---',
        '',
        "import { IconCheck, IconX, IconWrench } from '@posthog/icons'",
        '',
        '{/* Auto-generated file. Do not edit directly. */}',
        '{/* Generated from frontend/src/scenes/surveys/surveyVersionRequirements.ts */}',
        '{/* Run: pnpm --filter=@posthog/frontend build:survey-sdk-docs */}',
        '',
        'Not all survey features are available on every SDK. Web has the most complete support, while mobile SDKs have some limitations.',
        '',
        'For setup instructions, see the [installation guides](/docs/surveys/installation).',
        '',
    ]

    const headerCells = ['Feature', ...SDK_ORDER.map((sdk) => `[${SDK_INFO[sdk].name}](${SDK_INFO[sdk].docsUrl})`)]
    lines.push(`| ${headerCells.join(' | ')} |`)
    lines.push(`| ${headerCells.map(() => '---').join(' | ')} |`)

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

        lines.push(`| ${cells.join(' | ')} |`)
    }

    return lines.join('\n')
}

const outputPath = path.resolve(__dirname, '../../docs/published/products/surveys/sdk-feature-support.mdx')
const content = generateMarkdown()

fs.writeFileSync(outputPath, content, 'utf-8')
