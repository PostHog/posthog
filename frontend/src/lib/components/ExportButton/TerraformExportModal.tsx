import { useValues } from 'kea'

import { IconDownload, IconWarning } from '@posthog/icons'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { InsightModel } from '~/types'

import { HclExportResult, generateInsightHCLWithWarnings } from './hclExporter'

export interface TerraformExportModalProps {
    isOpen: boolean
    onClose: () => void
    insight: Partial<InsightModel>
}

export function TerraformExportModal({ isOpen, onClose, insight }: TerraformExportModalProps): JSX.Element {
    const { preflight } = useValues(preflightLogic)

    const result: HclExportResult = generateInsightHCLWithWarnings(insight, {
        includeImport: insight.id !== undefined,
    })

    const filename = `${insight.name || insight.derived_name || 'insight'}.tf`

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
    const isCloud = preflight?.cloud

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
                        Download {filename}
                    </LemonButton>
                </div>
            }
            width={720}
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

                {isCloud && (
                    <LemonBanner type="info">
                        You'll need to{' '}
                        <Link to="/settings/user-api-keys" target="_blank">
                            create a personal API key
                        </Link>{' '}
                        to authenticate the Terraform provider.
                    </LemonBanner>
                )}

                <CodeSnippet language={Language.Bash} wrap thing="Terraform configuration">
                    {result.hcl}
                </CodeSnippet>
            </div>
        </LemonModal>
    )
}
