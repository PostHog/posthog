import { IconDownload, IconWarning } from '@posthog/icons'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Link } from 'lib/lemon-ui/Link'

import { InsightModel } from '~/types'

import { HclExportResult } from './hclExporter'
import { generateInsightHCL } from './insightHclExporter'

export interface TerraformExportModalProps {
    isOpen: boolean
    onClose: () => void
    insight: Partial<InsightModel>
}

export function TerraformExportModal({ isOpen, onClose, insight }: TerraformExportModalProps): JSX.Element {
    const result: HclExportResult = generateInsightHCL(insight, {
        includeImport: insight.id !== undefined,
    })

    const baseName = insight.name || insight.derived_name || 'insight'
    const filename = `${baseName}.tf`
    const displayFilename = baseName.length > 30 ? `${baseName.slice(0, 30)}….tf` : filename

    const handleDownload = (): void => {
        const blob = new Blob([result.hcl], { type: 'text/plain' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
    }

    const providerDocsUrl = 'https://registry.terraform.io/providers/PostHog/posthog/latest/docs'
    const exampleRepoUrl =
        'https://github.com/PostHog/posthog/tree/master/terraform/us/project-2/team-analytics-platform'

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Manage with Terraform"
            description={
                <>
                    Use this configuration with the{' '}
                    <Link to={providerDocsUrl} target="_blank">
                        PostHog Terraform provider
                    </Link>{' '}
                    to manage this insight as code. See{' '}
                    <Link to={exampleRepoUrl} target="_blank">
                        how we use it internally
                    </Link>{' '}
                    for an example.
                </>
            }
            footer={
                <div className="flex justify-between w-full">
                    <LemonButton type="secondary" onClick={onClose}>
                        Close
                    </LemonButton>
                    <LemonButton type="primary" icon={<IconDownload />} onClick={handleDownload}>
                        Download {displayFilename}
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                {result.warnings.length > 0 && (
                    <LemonBanner type="warning">
                        <div className="flex items-start gap-2">
                            <IconWarning className="text-warning shrink-0 mt-0.5" />
                            <div>
                                <strong>Warnings:</strong>
                                <ul className="list-disc ml-4 mt-1 mb-0">
                                    {result.warnings.map((warning, index) => (
                                        <li key={index}>{warning}</li>
                                    ))}
                                </ul>
                            </div>
                        </div>
                    </LemonBanner>
                )}

                <CodeSnippet language={Language.HCL} wrap thing="Terraform configuration">
                    {result.hcl}
                </CodeSnippet>
            </div>
        </LemonModal>
    )
}
