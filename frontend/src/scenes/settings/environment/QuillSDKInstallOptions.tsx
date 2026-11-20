import {
    Badge,
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from '@posthog/quill'

import { WizardCommandBlock } from 'scenes/onboarding/shared/wizard-command/WizardCommandBlock'

import { SDKSetupInstructions } from './SDKSetupInstructions'

export function QuillSDKInstallOptions({
    showManualSetup,
    onShowManualSetupChange,
}: {
    showManualSetup: boolean
    onShowManualSetupChange: (open: boolean) => void
}): JSX.Element {
    return (
        <div className="flex max-w-200 flex-col gap-3">
            <Card size="sm">
                <CardHeader>
                    <CardTitle>Install with the setup agent</CardTitle>
                    <CardDescription>Run this command from the root of your project.</CardDescription>
                    <CardAction>
                        <Badge variant="success">Recommended</Badge>
                    </CardAction>
                </CardHeader>
                <CardContent>
                    <WizardCommandBlock />
                </CardContent>
            </Card>
            <Card size="sm" className="py-1">
                <Collapsible open={showManualSetup} onOpenChange={onShowManualSetupChange}>
                    <div className="px-1">
                        <CollapsibleTrigger
                            className="w-full justify-between font-semibold"
                            data-attr="sdk-setup-manual-toggle"
                        >
                            Set up manually
                        </CollapsibleTrigger>
                    </div>
                    <CollapsibleContent className="px-3 pt-2 pb-2">
                        <SDKSetupInstructions />
                    </CollapsibleContent>
                </Collapsible>
            </Card>
        </div>
    )
}
