import { IconDownload, IconWarning } from '@posthog/icons'

import { CodeSnippet, Language } from '~/lib/components/CodeSnippet/CodeSnippet'
import { LemonBanner } from '~/lib/lemon-ui/LemonBanner'
import { LemonButton } from '~/lib/lemon-ui/LemonButton'
import { LemonModal } from '~/lib/lemon-ui/LemonModal'
import { LemonSkeleton } from '~/lib/lemon-ui/LemonSkeleton'
import { Link } from '~/lib/lemon-ui/Link'

import {
    TerraformExportResource,
    TerraformExportResult,
    useTerraformDownload,
    useTerraformExport,
} from './useTerraformExport'

export type { TerraformExportResource }

interface TerraformExportModalProps {
    isOpen: boolean
    onClose: () => void
    resource: TerraformExportResource
}

function getBaseName(resource: TerraformExportResource): string {
    if (resource.type === 'dashboard') {
        return resource.data.name || `dashboard_${resource.data.id}`
    }
    return resource.data.name || resource.data.derived_name || 'insight'
}

function getDescription(resource: TerraformExportResource, result: TerraformExportResult | null): JSX.Element {
    const providerDocsUrl = 'https://registry.terraform.io/providers/PostHog/posthog/latest/docs'
    const exampleRepoUrl =
        'https://github.com/PostHog/posthog/tree/master/terraform/us/project-2/team-analytics-platform'

    const getExportPrefix = (): string => {
        const hasRelatedResources =
            result && (result.resourceCounts.alerts > 0 || result.resourceCounts.hogFunctions > 0)

        if (resource.type === 'dashboard' && result) {
            return `Export this dashboard and all related resources (${result.resourceCounts.insights} insight(s), ${result.resourceCounts.alerts} alert(s), ${result.resourceCounts.hogFunctions} destination(s)) to a Terraform configuration.`
        }
        if (resource.type === 'insight' && hasRelatedResources) {
            return `Export this insight and related resources (${result.resourceCounts.alerts} alert(s), ${result.resourceCounts.hogFunctions} destination(s)) to a Terraform configuration.`
        }
        return ''
    }

    const prefix = getExportPrefix()

    return (
        <>
            {prefix} Use this configuration with the{' '}
            <Link to={providerDocsUrl} target="_blank">
                PostHog Terraform provider
            </Link>{' '}
            to manage this {resource.type} as code. See{' '}
            <Link to={exampleRepoUrl} target="_blank">
                how we use it internally
            </Link>{' '}
            for an example.
        </>
    )
}

export function TerraformExportModal({ isOpen, onClose, resource }: TerraformExportModalProps): JSX.Element {
    const baseName = getBaseName(resource)
    const state = useTerraformExport(resource, isOpen)
    const handleDownload = useTerraformDownload(state.result, baseName)

    const filename = `${baseName}.tf`
    const displayFilename = baseName.length > 30 ? `${baseName.slice(0, 30)}….tf` : filename

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Manage with Terraform"
            description={getDescription(resource, state.result)}
            footer={
                <div className="flex justify-between w-full">
                    <LemonButton type="secondary" onClick={onClose}>
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        icon={<IconDownload />}
                        onClick={handleDownload}
                        disabledReason={state.loading ? 'Loading...' : state.error ? 'Export failed' : undefined}
                    >
                        Download {displayFilename}
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                {state.loading && (
                    <div className="space-y-2">
                        <LemonSkeleton className="h-4 w-1/2" />
                        <LemonSkeleton className="h-32" />
                    </div>
                )}

                {state.error && (
                    <LemonBanner type="error">
                        <div className="flex items-start gap-2">
                            <IconWarning className="text-danger shrink-0 mt-0.5" />
                            <div>
                                <strong>Error:</strong> {state.error}
                            </div>
                        </div>
                    </LemonBanner>
                )}

                {state.result && (
                    <>
                        {state.result.warnings.length > 0 && (
                            <LemonBanner type="warning">
                                <div className="flex items-start gap-2">
                                    <IconWarning className="text-warning shrink-0 mt-0.5" />
                                    <div>
                                        <strong>Warnings:</strong>
                                        <ul className="list-disc ml-4 mt-1 mb-0">
                                            {state.result.warnings.map((warning, index) => (
                                                <li key={index}>{warning}</li>
                                            ))}
                                        </ul>
                                    </div>
                                </div>
                            </LemonBanner>
                        )}

                        <CodeSnippet language={Language.HCL} wrap thing="Terraform configuration">
                            {state.result.hcl}
                        </CodeSnippet>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
