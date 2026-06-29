import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'

import { ExternalDataSourceType } from '~/queries/schema/schema-general'

import { SourceIcon } from './SourceIcon'

// Database sources the warehouse wizard can detect and connect from a codebase.
const WIZARD_DETECTABLE_SOURCES: ExternalDataSourceType[] = ['Postgres', 'MySQL', 'Supabase', 'MongoDB', 'BigQuery']

export function DataWarehouseWizardBlock(): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand('warehouse')

    // The wizard CLI only targets cloud (US/EU) and dev instances — self-hosted has no
    // preconfigured endpoint, so hide the block rather than show a command that can't work.
    if (!isCloudOrDev) {
        return <></>
    }

    return (
        <div className="flex flex-col gap-2 p-3 rounded-lg border border-primary bg-bg-light">
            <div className="flex items-center gap-2">
                <span className="font-semibold text-sm">Connect from your codebase</span>
                {WIZARD_DETECTABLE_SOURCES.map((type) => (
                    <SourceIcon key={type} type={type} size="small" disableTooltip />
                ))}
            </div>
            <p className="text-xs text-muted mb-1">
                Run this from your project root — the wizard auto-detects databases like Postgres, MySQL, Supabase,
                MongoDB and BigQuery and connects them for you.
            </p>
            <CommandBlock
                command={wizardCommand}
                copyLabel="Data warehouse wizard command"
                ariaLabel="Copy data warehouse wizard command"
                size="md"
                decoration="rainbow"
                className="bg-bg-light border border-border hover:border-primary"
            />
        </div>
    )
}
