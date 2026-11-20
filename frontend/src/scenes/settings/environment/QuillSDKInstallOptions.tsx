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
            <Card size="sm" className="gap-0 py-0">
                {/* The default collapsible tints itself and its trigger when open, which reads as a selected list row inside a card. */}
                <Collapsible
                    open={showManualSetup}
                    onOpenChange={onShowManualSetupChange}
                    className="hover:bg-transparent data-[open]:bg-transparent"
                >
                    <div className="p-1">
                        <CollapsibleTrigger
                            className="w-full justify-between font-semibold aria-expanded:bg-transparent"
                            data-attr="sdk-setup-manual-toggle"
                        >
                            Set up manually
                        </CollapsibleTrigger>
                    </div>
                    <CollapsibleContent className="border-t border-border p-3">
                        <SDKSetupInstructions />
                    </CollapsibleContent>
                </Collapsible>
            </Card>
        </div>
    )
}
