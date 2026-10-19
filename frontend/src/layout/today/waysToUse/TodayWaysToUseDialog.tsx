import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Button, Dialog, DialogBody, DialogContent, DialogFooter, cn } from '@posthog/quill'

import { WaysToUseDialogHeader } from './WaysToUseDialogHeader'
import { waysToUseLogic } from './waysToUseLogic'
import { WaysToUseSurfacesStep } from './WaysToUseSurfacesStep'
import { WaysToUseTeamStep } from './WaysToUseTeamStep'

export function TodayWaysToUseDialog(): JSX.Element {
    const { isOpen, steps, stepIndex, currentStep } = useValues(waysToUseLogic)
    const { closeWaysToUse, goToStep } = useActions(waysToUseLogic)
    const popupRef = useRef<HTMLDivElement>(null)
    const multiStep = steps.length > 1
    const lastStep = stepIndex >= steps.length - 1

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && closeWaysToUse('dismiss')}>
            <DialogContent
                ref={popupRef}
                size="wide"
                initialFocus={popupRef}
                className="group/popup lg:max-w-4xl"
                data-attr="today-ways-to-use-dialog"
                data-step={currentStep}
            >
                <WaysToUseDialogHeader />
                <DialogBody>{currentStep === 'team' ? <WaysToUseTeamStep /> : <WaysToUseSurfacesStep />}</DialogBody>
                <DialogFooter className={cn('items-center', multiStep ? 'sm:justify-between' : 'sm:justify-center')}>
                    {multiStep && (
                        <div
                            className="flex items-center gap-1.5"
                            role="img"
                            aria-label={`Step ${stepIndex + 1} of ${steps.length}`}
                        >
                            {steps.map((step, index) => (
                                <span
                                    key={step}
                                    className={cn(
                                        'h-1.5 rounded-full transition-all duration-300 ease-out motion-reduce:transition-none',
                                        index === stepIndex ? 'w-4 bg-primary' : 'w-1.5 bg-fill-selected'
                                    )}
                                />
                            ))}
                        </div>
                    )}
                    <div className="flex items-center gap-2">
                        {stepIndex > 0 && (
                            <Button
                                variant="outline"
                                onClick={() => goToStep(stepIndex - 1)}
                                data-attr="today-ways-to-use-back"
                            >
                                Back
                            </Button>
                        )}
                        {lastStep ? (
                            <Button
                                variant="primary"
                                onClick={() => closeWaysToUse('get_started')}
                                data-attr="today-ways-to-use-get-started"
                            >
                                Get started
                            </Button>
                        ) : (
                            <Button
                                variant="primary"
                                onClick={() => goToStep(stepIndex + 1)}
                                data-attr="today-ways-to-use-next"
                            >
                                Next
                            </Button>
                        )}
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
