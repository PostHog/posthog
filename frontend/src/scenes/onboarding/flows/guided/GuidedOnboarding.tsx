import { useActions, useMountedLogic, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { Button, Progress, TooltipProvider } from '@posthog/quill'

import { InstallChecklist } from './components/InstallChecklist'
import { PlanPreview } from './components/PlanPreview'
import { type GuidedStep, guidedOnboardingLogic } from './guidedOnboardingLogic'
import { DoneStep } from './steps/DoneStep'
import { EventsStep } from './steps/EventsStep'
import { FocusStep } from './steps/FocusStep'
import { GoalStep } from './steps/GoalStep'
import { GuidanceStep } from './steps/GuidanceStep'
import { IndustryStep } from './steps/IndustryStep'
import { InstallStep } from './steps/InstallStep'
import { McpStep } from './steps/McpStep'
import { PlatformStep } from './steps/PlatformStep'
import { ProjectStep } from './steps/ProjectStep'
import { WebsiteStep } from './steps/WebsiteStep'

const STEP_COMPONENTS: Record<GuidedStep, () => JSX.Element> = {
    guidance: GuidanceStep,
    project: ProjectStep,
    platform: PlatformStep,
    website: WebsiteStep,
    industry: IndustryStep,
    focus: FocusStep,
    goal: GoalStep,
    events: EventsStep,
    install: InstallStep,
    mcp: McpStep,
    done: DoneStep,
}

/** Prototype flow: a few short questions shape the install around one goal. */
export function GuidedOnboarding(): JSX.Element {
    useMountedLogic(guidedOnboardingLogic)
    const { step, stepIndex, guidance, progress } = useValues(guidedOnboardingLogic)
    const { back } = useActions(guidedOnboardingLogic)
    const Step = STEP_COMPONENTS[step]

    return (
        <TooltipProvider>
            <div data-quill className="min-h-screen bg-background text-foreground">
                {/* The question column stays centered on every step; the sidebar sits in the right gutter. */}
                <div className="mx-auto grid max-w-7xl grid-cols-1 gap-12 px-6 py-12 lg:grid-cols-[1fr_36rem_1fr] lg:py-16">
                    <div className="hidden lg:block" />
                    <main className="flex min-w-0 flex-col gap-8">
                        <div className="flex flex-col gap-3">
                            <div className="flex min-h-7 items-center">
                                {stepIndex > 0 && (
                                    <Button
                                        variant="link-muted"
                                        size="inline"
                                        onClick={back}
                                        data-attr="guided-onboarding-back"
                                    >
                                        <IconArrowLeft />
                                        Back
                                    </Button>
                                )}
                            </div>
                            <Progress value={progress * 100} />
                        </div>
                        <Step />
                    </main>
                    <aside className="hidden min-w-0 flex-col gap-4 lg:flex">
                        {step === 'install' && <InstallChecklist />}
                        {guidance === 'guided' && <PlanPreview />}
                    </aside>
                </div>
            </div>
        </TooltipProvider>
    )
}
