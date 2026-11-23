import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogHeader,
    DialogTitle,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
} from '@posthog/quill'
import type { StepDefinition } from '@posthog/shared-onboarding/steps'

import { LemonSelectSection } from 'lib/lemon-ui/LemonSelect/LemonSelect'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { OnboardingDocsContentWrapper } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'
import SetupWizardBanner from 'scenes/onboarding/shared/SetupWizardBanner'

import { SDKKey } from '~/types'

import type { SDK_CONFIGS } from './SDKSetupInstructions'

type SDKConfig = NonNullable<(typeof SDK_CONFIGS)[SDKKey]>

export function QuillSDKSetupInstructions({
    loading,
    config,
    options,
    selectedSDK,
    onSelectSDK,
    showFullSetup,
    setShowFullSetup,
    useReverseProxy,
    filterRequiredSteps,
}: {
    loading: boolean
    config: SDKConfig | undefined
    options: LemonSelectSection<SDKKey>[]
    selectedSDK: SDKKey
    onSelectSDK: (value: SDKKey) => void
    showFullSetup: boolean
    setShowFullSetup: (show: boolean) => void
    /** Client-side SDKs show the proxy host in their snippets. */
    useReverseProxy: boolean
    /** Trims the inline instructions to the required steps; the full setup dialog shows every step. */
    filterRequiredSteps: (steps: StepDefinition[]) => StepDefinition[]
}): JSX.Element | null {
    if (loading) {
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-4" />
                <Skeleton className="h-4" />
                <Skeleton className="h-4" />
            </div>
        )
    }

    if (!config) {
        return null
    }

    const { Installation, snippets, wizardIntegrationName, docsLink, name } = config
    const items = options.flatMap((section) =>
        section.options.flatMap((option) => ('value' in option ? [{ value: option.value, label: option.label }] : []))
    )

    return (
        <div className="flex max-w-200 flex-col gap-4">
            <Select<SDKKey> items={items} value={selectedSDK} onValueChange={(value) => value && onSelectSDK(value)}>
                <SelectTrigger className="w-full max-w-80">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {options.map((section) => (
                        <SelectGroup key={String(section.title)}>
                            <SelectGroupLabel>{section.title}</SelectGroupLabel>
                            {section.options.map((option) =>
                                'value' in option ? (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ) : null
                            )}
                        </SelectGroup>
                    ))}
                </SelectContent>
            </Select>
            <OnboardingDocsContentWrapper snippets={snippets} minimal useReverseProxy={useReverseProxy}>
                <Installation modifySteps={filterRequiredSteps} />
            </OnboardingDocsContentWrapper>
            <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" onClick={() => setShowFullSetup(true)}>
                    View full setup instructions
                </Button>
                <Button variant="link" nativeButton={false} render={<LinkPrimitive to={docsLink} target="_blank" />}>
                    {`${name} docs`}
                </Button>
            </div>
            <Dialog open={showFullSetup} onOpenChange={setShowFullSetup}>
                <DialogContent size="wide">
                    <DialogHeader>
                        <DialogTitle>{`${name} setup`}</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <div className="flex flex-col gap-4">
                            {wizardIntegrationName && <SetupWizardBanner integrationName={wizardIntegrationName} />}
                            <OnboardingDocsContentWrapper snippets={snippets} useReverseProxy={useReverseProxy}>
                                <Installation />
                            </OnboardingDocsContentWrapper>
                            <div>
                                <Button
                                    variant="link"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={docsLink} target="_blank" />}
                                >
                                    {`View full ${name} documentation`}
                                </Button>
                            </div>
                        </div>
                    </DialogBody>
                </DialogContent>
            </Dialog>
        </div>
    )
}
